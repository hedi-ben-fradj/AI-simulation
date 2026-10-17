"""Resource levels, personality modes and the setup API."""

import pytest
from fastapi.testclient import TestClient

from aisim.api.app import Settings, create_app
from aisim.config import load_config
from aisim.config.levels import LEVEL_IDS, describe_economy
from aisim.config.setup import SetupSettings, settings_to_overrides
from aisim.engine import Simulation

from .test_api_persistence import db_url  # noqa: F401


def econ(level, population):
    return describe_economy(load_config("default", {"resource_level": level, "simulation": {"population": population}}))


def test_levels_are_ordered_from_scarce_to_abundant():
    rows = [econ(lv, 6) for lv in LEVEL_IDS]
    ratios = [r["food_supply_vs_need"] for r in rows]
    prices = [r["meal_price"] for r in rows]
    work = [r["work_hours_for_food_per_day"] for r in rows]
    assert ratios == sorted(ratios) and prices == sorted(prices, reverse=True) and work == sorted(work, reverse=True)
    assert ratios[0] < 1 < ratios[3]  # scarce levels cannot feed everyone; normal can


@pytest.mark.parametrize("level", LEVEL_IDS)
def test_level_scales_with_population(level):
    small, large = econ(level, 2), econ(level, 20)
    assert abs(small["food_supply_vs_need"] - large["food_supply_vs_need"]) < 0.35
    assert small["meal_price"] == large["meal_price"]


def test_explicit_overrides_beat_the_level():
    cfg = load_config("default", {"resource_level": "scarce", "resources": {"food_price": 9}})
    assert cfg.resources.food_price == 9
    assert cfg.work.base_wage_per_tick == 4.0  # still from the level


def test_unknown_level_rejected():
    with pytest.raises(ValueError):
        load_config("default", {"resource_level": "plenty"})


def make(settings: SetupSettings) -> Simulation:
    return Simulation.create(load_config("default", settings_to_overrides(settings)), "w")


def test_identical_personality_mode():
    sim = make(SetupSettings(population=4, personality_mode="identical"))
    for a in sim.world.agents.values():
        assert set(a.personality.values()) == {0.5}


def test_identical_mode_with_custom_means():
    sim = make(SetupSettings(population=3, personality_mode="identical", trait_means={"spirituality": 0.9}))
    assert all(a.personality["spirituality"] == 0.9 and a.personality["humor"] == 0.5 for a in sim.world.agents.values())


def test_random_uniform_mode_respects_deviation():
    sim = make(SetupSettings(population=30, personality_mode="random", personality_distribution="uniform",
                             personality_deviation=0.1))
    values = [v for a in sim.world.agents.values() for v in a.personality.values()]
    assert min(values) >= 0.4 - 1e-9 and max(values) <= 0.6 + 1e-9
    assert len(set(values)) > 10


def test_random_normal_mode_spread_grows_with_deviation():
    def spread(dev):
        sim = make(SetupSettings(population=30, personality_deviation=dev))
        vals = [a.personality["ambition"] for a in sim.world.agents.values()]
        return max(vals) - min(vals)

    assert spread(0.3) > spread(0.05)


def test_two_agents_world_runs_and_small_world():
    sim = make(SetupSettings(population=2, resource_level="very_scarce", days=2))
    assert sim.config.world.width == 60 and sim.config.simulation.max_ticks == 48
    for _ in range(48):
        sim.step()
    assert len(sim.world.agents) == 2


def test_population_bounds():
    with pytest.raises(ValueError):
        SetupSettings(population=1)
    with pytest.raises(ValueError):
        SetupSettings(trait_means={"luck": 0.5})


def test_setup_api(db_url):  # noqa: F811
    with TestClient(create_app(Settings(database_url=db_url))) as c:
        opts = c.get("/api/setup/options").json()
        assert [lv["id"] for lv in opts["resource_levels"]] == LEVEL_IDS
        preview = c.post("/api/setup/preview", json={"population": 3, "resource_level": "very_scarce",
                                                     "personality_mode": "identical"}).json()
        assert preview["economy"]["food_supply_vs_need"] < 1 and preview["warnings"]
        assert len(preview["agents"]) == 3 and preview["traits"]["humor"] == {"mean": 0.5, "min": 0.5, "max": 0.5}
        assert c.post("/api/setup/preview", json={"population": 1}).status_code == 422
        w = c.post("/api/setup/worlds", json={"name": "Pair", "population": 2, "resource_level": "abundant",
                                              "start": False}).json()
        assert w["name"] == "Pair" and len(w["agents"]) == 2 and w["status"] == "paused"
        cfg = c.get(f"/api/worlds/{w['id']}/config").json()
        assert cfg["resource_level"] == "abundant" and cfg["resources"]["food_price"] == 1.5

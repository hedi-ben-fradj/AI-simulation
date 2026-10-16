import pytest

from aisim.analysis.behavior import analyse_world, pearson
from aisim.config import load_config
from aisim.engine import Simulation


def test_pearson():
    assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)
    assert pearson([1, 1, 1], [1, 2, 3]) is None
    assert pearson([1, 2], [1, 2]) is None


def test_rule_agents_traits_drive_behaviour():
    cfg = load_config("abundance", {"simulation": {"population": 16, "max_agents": 20},
                                    "personality": {"initial_spread": 0.25}})
    sim = Simulation.create(cfg, "w")
    for _ in range(24 * 6):
        sim.step()
    result = analyse_world(sim)
    hyps = {(h["trait"], h["behaviour"]): h for h in result["correlations"]["hypotheses"]}
    assert hyps[("sociability", "social_share")]["supported"]
    assert hyps[("spirituality", "existential_activation_rate")]["supported"]
    assert result["existential"]["activation_rate"] > 0
    # Analysis uses birth traits, not drifted ones.
    row = result["behaviour"][0]
    assert row["traits"] == sim.world.agents[row["agent_id"]].initial_personality


def test_metrics_include_trait_means():
    sim = Simulation.create(load_config(), "w")
    m = sim.step().metrics
    assert set(m["traits_mean"]) >= {"spirituality", "generosity"}

"""Unit tests for deterministic world rules (Priority 1 of the spec)."""

import pytest

from aisim.config import load_config
from aisim.engine import Simulation
from aisim.engine.actions import ActionProposal
from aisim.engine.validation import validate_action

from .conftest import make_sim, place, run_action


def test_time_advances_one_tick_per_step(sim):
    assert sim.tick == 0
    sim.step()
    sim.step()
    assert sim.tick == 2
    assert sim.time_label(0) == "Day 1, 00:00"
    assert sim.time_label(25) == "Day 2, 01:00"


def test_configurable_ticks_per_day():
    s = make_sim({"simulation": {"ticks_per_day": 96}})
    assert s.time_label(4) == "Day 1, 01:00"


def test_hunger_increases_and_passive_energy_drain(sim):
    a = sim.world.agents["a1"]
    run_action(sim, "a1", ActionProposal(action="idle"))
    cfg = sim.config.resources
    assert a.hunger == pytest.approx(cfg.hunger_increase_per_tick)
    assert a.energy == pytest.approx(cfg.starting_energy - cfg.passive_energy_drain_per_tick)


def test_work_reward_and_costs(sim):
    a = sim.world.agents["a1"]
    loc = place(sim, a, "workplace")
    tokens0, energy0 = a.tokens, a.energy
    result, records = run_action(sim, "a1", ActionProposal(action="work", duration=1))
    wc = sim.config.work
    assert records["a1"].valid
    assert a.tokens == pytest.approx(tokens0 + wc.base_wage_per_tick * loc.wage_multiplier)
    expected_energy = energy0 - wc.energy_cost_per_tick - sim.config.resources.passive_energy_drain_per_tick
    assert a.energy == pytest.approx(expected_energy)
    assert a.work_ticks_today == 1
    assert any(e.type == "work" for e in result.events)


def test_fatigued_work_costs_health_and_is_less_productive(sim):
    a = sim.world.agents["a1"]
    place(sim, a, "workplace")
    a.energy = 25  # below fatigue threshold (30)
    tokens0, health0 = a.tokens, a.health
    run_action(sim, "a1", ActionProposal(action="work", duration=1))
    wc = sim.config.work
    assert a.tokens - tokens0 == pytest.approx(wc.base_wage_per_tick * wc.low_energy_productivity)
    workload = wc.fatigue_workload_multiplier
    expected_health_cost = (workload - wc.safe_workload) * wc.health_penalty_rate
    assert health0 - a.health == pytest.approx(expected_health_cost)


def test_work_requires_travel_when_not_at_workplace(sim):
    a = sim.world.agents["a1"]
    loc = next(l for l in sim.world.locations.values() if l.type == "workplace")
    a.x, a.y = loc.x + 40 if loc.x < 50 else loc.x - 40, loc.y
    tokens0 = a.tokens
    run_action(sim, "a1", ActionProposal(action="work", duration=1))
    assert a.tokens == tokens0  # travelled this tick
    assert a.current_task is not None and a.current_task.action == "work"


def test_eating_reduces_hunger_and_costs_tokens(sim):
    a = sim.world.agents["a1"]
    loc = place(sim, a, "food")
    a.hunger = 60
    tokens0, stock0 = a.tokens, loc.stock
    run_action(sim, "a1", ActionProposal(action="eat"))
    rc = sim.config.resources
    assert a.hunger == pytest.approx(max(0, 60 - rc.food_nutrition) + rc.hunger_increase_per_tick)
    assert a.tokens == pytest.approx(tokens0 - loc.price)
    assert loc.stock == stock0 - 1


def test_eating_from_inventory_needs_no_location_or_tokens(sim):
    a = sim.world.agents["a1"]
    a.food, a.tokens, a.hunger = 1, 0, 50
    run_action(sim, "a1", ActionProposal(action="eat"))
    assert a.food == 0
    assert a.hunger == pytest.approx(20 + sim.config.resources.hunger_increase_per_tick)


def test_cannot_buy_food_without_tokens(sim):
    a = sim.world.agents["a1"]
    place(sim, a, "food")
    a.tokens = 0
    sim.begin_tick()
    result = validate_action(sim, a, ActionProposal(action="eat"))
    assert not result.ok and result.reason == "insufficient_tokens"


def test_rest_recovers_energy_more_at_rest_area(sim):
    a, b = sim.world.agents["a1"], sim.world.agents["a2"]
    place(sim, a, "rest")
    b.x, b.y = 0, 0
    a.energy = b.energy = 40
    run_action(sim, "a1", ActionProposal(action="rest", duration=1),
               others={"a2": ActionProposal(action="rest", duration=1)})
    rc = sim.config.resources
    assert a.energy == pytest.approx(40 + rc.rest_energy_recovery_per_tick * rc.rest_area_recovery_multiplier)
    assert b.energy == pytest.approx(40 + rc.rest_energy_recovery_per_tick)


def test_starvation_damages_health_and_kills():
    s = make_sim({"resources": {"max_critical_hunger_ticks": 1000}})
    a = s.world.agents["a1"]
    a.hunger, a.health, a.tokens = 100, 6, 0
    result, _ = run_action(s, "a1", ActionProposal(action="idle"))
    assert a.alive
    assert a.health == pytest.approx(6 - s.config.resources.starvation_damage_per_tick)
    result, _ = run_action(s, "a1", ActionProposal(action="idle"))
    assert not a.alive
    assert a.death["cause"] == "starvation"
    assert result.deaths and result.deaths[0]["agent_id"] == "a1"
    assert any(e.type == "death" for e in result.events)


def test_prolonged_critical_hunger_kills():
    s = make_sim({"resources": {"max_critical_hunger_ticks": 2, "starvation_damage_per_tick": 0}})
    a = s.world.agents["a1"]
    a.hunger = 100
    for _ in range(3):
        run_action(s, "a1", ActionProposal(action="idle"))
    assert not a.alive and a.death["cause"] == "prolonged_starvation"


def test_dead_agents_get_no_decisions_and_cannot_act(sim):
    a = sim.world.agents["a1"]
    a.alive = False
    requests = sim.begin_tick()
    assert all(r.agent_id != "a1" for r in requests)
    assert validate_action(sim, a, ActionProposal(action="idle")).reason == "agent_is_dead"


def test_validation_rejects_unknown_and_impossible_actions(sim):
    a = sim.world.agents["a1"]
    sim.begin_tick()
    assert validate_action(sim, a, ActionProposal(action="fly")).reason == "unknown_action"
    a.energy = 2
    assert validate_action(sim, a, ActionProposal(action="explore")).reason == "insufficient_energy"
    a.energy = 100
    assert validate_action(sim, a, ActionProposal(action="give", target="a2",
                                                  resource_offer={"tokens": 1000})).reason == "insufficient_resources"
    assert validate_action(sim, a, ActionProposal(action="give", target="nobody")).reason == "invalid_target"
    assert validate_action(sim, a, ActionProposal(action="give", target="a1",
                                                  resource_offer={"tokens": 1})).reason == "invalid_target"


def test_duration_is_clamped_to_maximum(sim):
    a = sim.world.agents["a1"]
    place(sim, a, "workplace")
    sim.begin_tick()
    result = validate_action(sim, a, ActionProposal(action="work", duration=50))
    assert result.ok
    assert result.task.total_ticks == sim.config.capacity.max_task_duration_ticks
    assert "duration_clamped" in result.notes


def test_daily_work_capacity_enforced(sim):
    a = sim.world.agents["a1"]
    place(sim, a, "workplace")
    a.work_ticks_today = a.work_capacity
    sim.begin_tick()
    assert validate_action(sim, a, ActionProposal(action="work")).reason == "work_capacity_exhausted"


def test_workplace_capacity_limits_workers():
    s = make_sim({"simulation": {"population": 3}, "world": {"workplace_capacity": 1, "workplaces": 1}})
    loc = next(l for l in s.world.locations.values() if l.type == "workplace")
    for a in s.world.agents.values():
        a.x, a.y = loc.x, loc.y
    s.begin_tick()
    s.apply_decisions({aid: ActionProposal(action="work", duration=1) for aid in s.world.agents})
    result = s.advance()
    assert sum(1 for e in result.events if e.type == "work") == 1
    assert sum(1 for e in result.events if e.type == "action_failed") == 2


def test_invalid_proposal_gets_fallback_and_is_recorded(sim):
    a = sim.world.agents["a1"]
    _, records = run_action(sim, "a1", ActionProposal(action="teleport", source="llm"))
    rec = records["a1"]
    assert not rec.valid and rec.reason == "unknown_action"
    assert rec.fallback_reason == "invalid_proposal"
    assert rec.applied_action != "teleport"
    assert a.last_failure.startswith("teleport")


def test_missing_decision_uses_fallback(sim):
    sim.begin_tick()
    records = sim.apply_decisions({}, meta={"a1": {"fallback_reason": "timeout"}})
    rec = next(r for r in records if r.agent_id == "a1")
    assert rec.source == "fallback" and rec.fallback_reason == "timeout"


def test_multi_tick_task_does_not_request_new_decisions(sim):
    a = sim.world.agents["a1"]
    place(sim, a, "rest")
    a.energy = 10
    run_action(sim, "a1", ActionProposal(action="rest", duration=3))
    requests = sim.begin_tick()
    assert all(r.agent_id != "a1" for r in requests)


def test_food_restocks_at_end_of_day():
    s = make_sim()
    loc = next(l for l in s.world.locations.values() if l.type == "food")
    loc.stock = 0
    for _ in range(s.config.simulation.ticks_per_day):
        s.step(lambda sim, r: ActionProposal(action="idle"))
    assert loc.stock == min(loc.max_stock, loc.restock_per_day)


def test_same_seed_is_reproducible():
    cfg = load_config("default", {"simulation": {"population": 6}})
    s1, s2 = Simulation.create(cfg, "x"), Simulation.create(cfg, "x")
    for _ in range(60):
        r1, r2 = s1.step(), s2.step()
    assert s1.snapshot() == s2.snapshot()
    assert r1.metrics == r2.metrics


def test_different_seeds_diverge():
    s1 = Simulation.create(load_config("default", {"simulation": {"random_seed": 1}}), "x")
    s2 = Simulation.create(load_config("default", {"simulation": {"random_seed": 2}}), "x")
    for _ in range(30):
        s1.step()
        s2.step()
    assert s1.snapshot() != s2.snapshot()


def test_snapshot_restore_continues_identically():
    cfg = load_config("default", {"simulation": {"population": 5}})
    s1 = Simulation.create(cfg, "x")
    for _ in range(30):
        s1.step()
    restored = Simulation.from_snapshot(cfg, s1.snapshot())
    for _ in range(30):
        r1, r2 = s1.step(), restored.step()
    assert s1.snapshot() == restored.snapshot()


def test_resources_never_negative_over_long_run():
    for preset in ("default", "scarcity", "abundance"):
        s = Simulation.create(load_config(preset, {"simulation": {"population": 8}}), "x")
        for _ in range(24 * 6):
            s.step()
            for a in s.world.agents.values():
                assert a.tokens >= -1e-6, (preset, a.name, a.tokens)
                assert a.food >= 0
                assert 0 <= a.energy <= s.config.resources.maximum_energy
                assert 0 <= a.health <= s.config.resources.maximum_health
                assert 0 <= a.hunger <= s.config.resources.maximum_hunger
            for loc in s.world.locations.values():
                assert loc.stock is None or loc.stock >= 0


def test_death_is_permanent_unless_replacement_enabled():
    s = make_sim({"simulation": {"enable_replacement": True}})
    a = s.world.agents["a1"]
    a.health = 0.5
    a.hunger = 100
    run_action(s, "a1", ActionProposal(action="idle"))
    assert not a.alive
    assert len(s.world.alive_agents()) == 3

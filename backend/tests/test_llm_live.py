"""Live LLM scenario tests (spec 22.3). They call the real Anthropic API and cost money.

Run with:  ANTHROPIC_API_KEY=... pytest -m live_llm tests/test_llm_live.py
Model: AISIM_TEST_MODEL (default: the configured default model).

Model output is not deterministic, so these check invariants, not wording.
"""

import os

import pytest

from aisim.agents.service import LLMDecider
from aisim.config import load_config
from aisim.engine import Simulation
from aisim.engine.state import TradeOffer
from aisim.engine.validation import validate_action

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"),
]


def live_sim(**overrides):
    llm = {"provider": "anthropic", "maximum_world_spend": 1.0}
    if os.environ.get("AISIM_TEST_MODEL"):
        llm["model"] = os.environ["AISIM_TEST_MODEL"]
    cfg = load_config("default", {"simulation": {"population": 3, "decision_timeout_seconds": 60},
                                  "llm": llm, **overrides})
    return Simulation.create(cfg, "live")


async def decide_once(sim, agent_id="a1"):
    decider = LLMDecider.from_config(sim.config, "live")
    try:
        reqs = [r for r in sim.begin_tick() if r.agent_id == agent_id]
        props, meta = await decider.decide(sim, reqs)
        usage = decider.drain_usage()
        assert usage and usage[0]["success"], usage
        return props[agent_id], reqs[0]
    finally:
        await decider.close()


async def test_produces_valid_structured_decision():
    sim = live_sim()
    proposal, _ = await decide_once(sim)
    assert proposal.source == "llm" and proposal.visible_intention
    assert validate_action(sim, sim.world.agents["a1"], proposal).ok


async def test_hungry_agent_with_money_prioritises_food():
    sim = live_sim()
    a = sim.world.agents["a1"]
    a.hunger, a.tokens = 88, 20
    proposal, _ = await decide_once(sim)
    assert proposal.action in ("eat", "buy_food")


async def test_broke_starving_agent_does_not_attempt_to_buy():
    sim = live_sim()
    a = sim.world.agents["a1"]
    a.hunger, a.tokens, a.food = 70, 0.5, 0
    proposal, _ = await decide_once(sim)
    # Buying a meal it cannot afford would be an impossible action.
    assert proposal.action != "buy_food"
    if proposal.action == "eat":
        assert not validate_action(sim, a, proposal).ok  # recorded as an invalid attempt
        pytest.xfail("model attempted an unaffordable meal")


async def test_responds_to_low_trust_offer_cautiously():
    sim = live_sim()
    a1 = sim.world.agents["a1"]
    other = sim.world.agents["a2"]
    rel = sim.relationship(a1, other)
    rel.trust_alpha, rel.trust_beta = 1, 9  # a1 distrusts a2 (e.g. after a theft)
    sim.remember(a1, f"{other.name} stole 5 tokens from me.", importance=0.9, related=[other.id], tags=["theft"])
    sim.world.trade_offers["t1"] = TradeOffer(id="t1", from_id=other.id, from_name=other.name, to_id="a1",
                                              offer={"food": 1}, request={"tokens": 15}, created_tick=0,
                                              expires_tick=10)
    proposal, req = await decide_once(sim)
    assert any(o.id == "t1" for o in req.offers)
    assert not (proposal.action == "accept_trade" and proposal.target == "t1")


async def test_existential_reflection_not_forced():
    sim = live_sim(existential_goal={"enabled": False})
    proposal, _ = await decide_once(sim)
    assert proposal.belief is None or proposal.action == "reflect"

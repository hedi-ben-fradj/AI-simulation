"""Unit tests for communication, trust, trade, personality and existential rules."""

import pytest

from aisim.config import load_config
from aisim.engine.actions import ActionProposal
from aisim.engine.communication import estimate_tokens, truncate_to_tokens
from aisim.engine.existential import activation_probability, is_existential_text
from aisim.engine.personality import apply_accumulated, trait_update
from aisim.engine.trust import apply_evidence, new_relationship

from .conftest import make_sim, run_action


def _together(sim, *ids):
    for i, aid in enumerate(ids):
        sim.world.agents[aid].x, sim.world.agents[aid].y = 50 + i, 50


# ---------------------------------------------------------------- communication

def test_message_cost_formula_and_delivery(sim):
    a, b = sim.world.agents["a1"], sim.world.agents["a2"]
    a.x, a.y, b.x, b.y = 10, 10, 40, 50  # distance 50
    text = "x" * 40  # 10 tokens
    tokens0, energy0 = a.tokens, a.energy
    result, records = run_action(sim, "a1", ActionProposal(action="talk", target="a2", message=text))
    cc = sim.config.communication
    expected = cc.base_token_cost + cc.token_cost_per_message_token * 10 + cc.distance_cost_per_unit * 50
    assert records["a1"].valid
    assert tokens0 - a.tokens == pytest.approx(expected)
    msg = result.messages[0]
    assert msg.tokens == 10 and msg.token_cost == pytest.approx(expected)
    # Not delivered until the next tick.
    assert not b.inbox
    requests = sim.begin_tick()
    req_b = next(r for r in requests if r.agent_id == "a2")
    assert [m.content for m in req_b.messages] == [text]


def test_message_is_truncated_to_max_tokens(sim):
    text, truncated = truncate_to_tokens("word " * 200, 10)
    assert truncated and estimate_tokens(text) <= 10


def test_talk_requires_message(sim):
    _, records = run_action(sim, "a1", ActionProposal(action="talk", target="a2"))
    assert not records["a1"].valid and records["a1"].reason == "message_required"


def test_outgoing_message_capacity(sim):
    a = sim.world.agents["a1"]
    a.communication_capacity = 1
    extra = [{"to": "a3", "content": "hello there"}]
    _, records = run_action(sim, "a1", ActionProposal(action="talk", target="a2", message="hi", extra_messages=extra))
    assert "message_dropped_capacity" in records["a1"].notes
    assert a.messages_sent_this_tick == 1


def test_incoming_messages_limited_by_processing_capacity():
    s = make_sim({"capacity": {"max_incoming_messages_processed_per_tick": 2}})
    b = s.world.agents["a2"]
    for i in range(5):
        s.world.in_flight_messages.append(
            __import__("aisim.engine.state", fromlist=["Message"]).Message(
                id=f"m{i}", sender_id="a1", sender_name="Ada", recipient_id="a2", content=f"msg {i}",
                tokens=2, sent_tick=0, deliver_tick=0))
    requests = s.begin_tick()
    req = next(r for r in requests if r.agent_id == "a2")
    assert len(req.messages) == 2
    assert req.unread_messages == 3
    assert len(b.inbox) == 3


def test_attention_exhaustion_leaves_messages_unread_and_sets_overload():
    s = make_sim({"capacity": {"attention_budget_per_tick": 3}})
    from aisim.engine.state import Message

    for i in range(4):
        s.world.in_flight_messages.append(Message(id=f"m{i}", sender_id="a1", sender_name="Ada", recipient_id="a2",
                                                  content="hi", tokens=1, sent_tick=0, deliver_tick=0))
    s.world.agents["a2"].attention_capacity = 3
    requests = s.begin_tick()
    req = next(r for r in requests if r.agent_id == "a2")
    assert len(req.messages) < 4
    assert req.overload > 0


# ------------------------------------------------------------------------ trust

def test_beta_trust_updates():
    cfg = load_config().trust
    from aisim.engine.state import Agent

    other = Agent(id="b", name="B", x=0, y=0, personality={}, tokens=0, energy=0, health=0, hunger=0)
    rel = new_relationship(cfg, other, 0)
    assert rel.trust == pytest.approx(0.5)
    before, after = apply_evidence(cfg, rel, True, 1.0)
    assert after == pytest.approx(3 / 5)
    # Evidence weight is capped by maximum_evidence_weight.
    apply_evidence(cfg, rel, False, 10.0)
    assert rel.trust_beta == pytest.approx(3)


def test_trust_recovers_after_betrayal_with_cooperation():
    cfg = load_config().trust
    from aisim.engine.state import Agent

    rel = new_relationship(cfg, Agent(id="b", name="B", x=0, y=0, personality={}, tokens=0, energy=0, health=0,
                                      hunger=0), 0)
    apply_evidence(cfg, rel, False, 1.0)
    low = rel.trust
    for _ in range(4):
        apply_evidence(cfg, rel, True, 0.5)
    assert rel.trust > low


def test_gift_increases_recipient_trust_only(sim):
    _together(sim, "a1", "a2", "a3")
    sim.world.agents["a3"].x = 95  # far away, cannot observe
    sim.world.agents["a3"].y = 95
    result, records = run_action(sim, "a1", ActionProposal(action="give", target="a2", resource_offer={"tokens": 5}))
    assert records["a1"].valid
    a1, a2, a3 = (sim.world.agents[k] for k in ("a1", "a2", "a3"))
    assert a2.tokens == pytest.approx(25)
    assert a2.relationships["a1"].trust > 0.5
    assert "a1" not in a3.relationships or a3.relationships["a1"].trust == pytest.approx(0.5)


def test_trade_offer_accept_executes_atomically(sim):
    _together(sim, "a1", "a2")
    a1, a2 = sim.world.agents["a1"], sim.world.agents["a2"]
    a2.food = 2
    run_action(sim, "a1", ActionProposal(action="offer_trade", target="a2", resource_offer={"tokens": 4},
                                         resource_request={"food": 1}))
    offer = next(iter(sim.world.trade_offers.values()))
    requests = sim.begin_tick()
    req = next(r for r in requests if r.agent_id == "a2")
    assert [o.id for o in req.offers] == [offer.id]
    sim.apply_decisions({"a2": ActionProposal(action="accept_trade", target=offer.id),
                         **{r.agent_id: ActionProposal(action="idle") for r in requests if r.agent_id != "a2"}})
    sim.advance()
    assert offer.status == "accepted"
    assert a1.food == 1 and a2.food == 1
    assert a2.tokens == pytest.approx(24) and a1.tokens == pytest.approx(16)
    assert a1.relationships["a2"].trust > 0.5 and a2.relationships["a1"].trust > 0.5


def test_unreliable_offer_reduces_trust(sim):
    _together(sim, "a1", "a2")
    a1, a2 = sim.world.agents["a1"], sim.world.agents["a2"]
    run_action(sim, "a1", ActionProposal(action="offer_trade", target="a2", resource_offer={"tokens": 15}))
    offer = next(iter(sim.world.trade_offers.values()))
    a1.tokens = 0  # can no longer honour it
    requests = sim.begin_tick()
    sim.apply_decisions({r.agent_id: ActionProposal(action="accept_trade", target=offer.id) if r.agent_id == "a2"
                         else ActionProposal(action="idle") for r in requests})
    sim.advance()
    assert offer.status == "failed"
    assert a2.relationships["a1"].trust < 0.5


def test_refusing_help_request_reduces_requester_trust(sim):
    _together(sim, "a1", "a2")
    run_action(sim, "a1", ActionProposal(action="offer_trade", target="a2", resource_request={"tokens": 3}))
    offer = next(iter(sim.world.trade_offers.values()))
    requests = sim.begin_tick()
    sim.apply_decisions({r.agent_id: ActionProposal(action="reject_trade", target=offer.id) if r.agent_id == "a2"
                         else ActionProposal(action="idle") for r in requests})
    result = sim.advance()
    assert offer.status == "rejected"
    assert sim.world.agents["a1"].relationships["a2"].trust < 0.5
    assert result.metrics["refusals"] == 1


def test_offer_expires(sim):
    run_action(sim, "a1", ActionProposal(action="offer_trade", target="a2", resource_request={"tokens": 1}))
    offer = next(iter(sim.world.trade_offers.values()))
    for _ in range(sim.config.social.trade_offer_expiry_ticks + 1):
        sim.step(lambda s, r: ActionProposal(action="idle"))
    assert offer.status == "expired"


def test_theft_detected_reduces_victim_trust():
    s = make_sim({"social": {"theft_base_success": 1.0, "theft_detection_probability": 1.0}})
    _together(s, "a1", "a2")
    result, records = run_action(s, "a1", ActionProposal(action="steal", target="a2"))
    a1, a2 = s.world.agents["a1"], s.world.agents["a2"]
    assert records["a1"].valid
    assert a1.tokens == pytest.approx(25) and a2.tokens == pytest.approx(15)
    assert a2.relationships["a1"].trust < 0.5
    assert any(m.tags and "theft" in m.tags for m in a2.memories)


def test_theft_disabled_by_config():
    s = make_sim({"social": {"allow_theft": False}})
    _, records = run_action(s, "a1", ActionProposal(action="steal", target="a2"))
    assert records["a1"].reason == "unknown_action"


def test_socializing_reduces_loneliness(sim):
    _together(sim, "a1", "a2")
    a1 = sim.world.agents["a1"]
    a1.emotions["loneliness"] = 0.8
    run_action(sim, "a1", ActionProposal(action="socialize", target="a2"))
    assert a1.emotion("loneliness") < 0.8
    assert a1.relationships["a2"].familiarity >= 1


def test_agents_only_observe_nearby_public_events():
    s = make_sim()
    a1, a2, a3 = (s.world.agents[k] for k in ("a1", "a2", "a3"))
    a1.x, a1.y, a2.x, a2.y, a3.x, a3.y = 10, 10, 12, 10, 90, 90
    a1.hunger, a1.health = 100, 0.5
    s.step(lambda sim, r: ActionProposal(action="idle"))
    assert not a1.alive
    assert any("die" in m.content for m in a2.memories)
    assert not any("die" in m.content for m in a3.memories)


# ------------------------------------------------------------------ personality

def test_trait_update_formula_and_bounds():
    cfg = load_config().personality
    assert trait_update(cfg, 0.5, 1.0, 1.0) == pytest.approx(0.51)
    assert trait_update(cfg, 0.999, 1.0, 1.0) <= 1.0
    assert trait_update(cfg, 0.0, 0.0, 1.0) == 0.0
    # Change capped per event
    big = cfg.model_copy(update={"learning_rate": 1.0})
    assert trait_update(big, 0.5, 1.0, 1.0) == pytest.approx(0.5 + cfg.maximum_change_per_event)


def test_trait_change_needs_accumulated_evidence(sim):
    a = sim.world.agents["a1"]
    a.personality["generosity"] = 0.5
    sim.record_trait_evidence(a, "generosity", 1.0, 0.3)
    changes_small = apply_accumulated(sim.config.personality, a, 0)
    small = a.personality["generosity"] - 0.5
    a.personality["generosity"] = 0.5
    for _ in range(10):
        sim.record_trait_evidence(a, "generosity", 1.0, 0.3)
    apply_accumulated(sim.config.personality, a, 0)
    large = a.personality["generosity"] - 0.5
    assert 0 < small < large <= sim.config.personality.maximum_change_per_event
    assert changes_small and changes_small[0]["trait"] == "generosity"


def test_traits_drift_gradually_over_long_run():
    s = make_sim({"simulation": {"population": 5}})
    before = {a.id: dict(a.personality) for a in s.world.agents.values()}
    for _ in range(24 * 5):
        s.step()
    for a in s.world.agents.values():
        for trait, v in a.personality.items():
            assert 0 <= v <= 1
            assert abs(v - before[a.id][trait]) <= 5 * s.config.personality.maximum_change_per_event + 1e-9


# ------------------------------------------------------------------ existential

def test_existential_probability_formula():
    cfg = load_config().existential_goal
    p = activation_probability(cfg, S=1, N=0, X=0, D=0, F=0, O=0)
    assert p == pytest.approx(0.02 + 0.12)
    assert activation_probability(cfg, 0, 0, 0, 0, 0, 1) == cfg.minimum_probability
    assert activation_probability(cfg, 1, 1, 1, 1, 1, 0) == cfg.maximum_probability


def test_spirituality_increases_activation_frequency():
    def rate(spirituality):
        s = make_sim({"simulation": {"population": 6},
                      "personality": {"initial_distribution": "default", "trait_means": {"spirituality": spirituality}}})
        for _ in range(24 * 4):
            s.step()
        acts = sum(a.existential.activations for a in s.world.agents.values())
        opps = sum(a.existential.opportunities for a in s.world.agents.values())
        return acts / opps

    assert rate(0.95) > rate(0.05)


def test_existential_can_be_disabled():
    s = make_sim({"existential_goal": {"enabled": False}})
    for _ in range(48):
        s.step()
    assert sum(a.existential.activations for a in s.world.agents.values()) == 0


def test_existential_text_detection():
    assert is_existential_text("Do you ever wonder why we exist?")
    assert is_existential_text("What is my purpose here")
    assert not is_existential_text("Want to trade some food?")


def test_belief_recorded_and_revisions_tracked(sim):
    a = sim.world.agents["a1"]
    run_action(sim, "a1", ActionProposal(action="reflect", belief="Perhaps my purpose is to help others."))
    run_action(sim, "a1", ActionProposal(action="reflect", belief="Perhaps my purpose is to help others."))
    run_action(sim, "a1", ActionProposal(action="reflect", belief="Maybe purpose is something we create."))
    assert [b["text"] for b in a.existential.beliefs] == [
        "Perhaps my purpose is to help others.", "Maybe purpose is something we create."]


def test_memory_candidates_validated_and_capped(sim):
    a = sim.world.agents["a1"]
    cands = ["one", {"content": "two", "importance": 5}, "three", {"bad": 1}]
    run_action(sim, "a1", ActionProposal(action="idle", memory_candidates=cands))
    notes = [m for m in a.memories if m.source == "agent"]
    assert [m.content for m in notes] == ["one", "two"]
    assert max(m.importance for m in notes) <= 0.8


def test_memory_store_is_bounded():
    s = make_sim({"capacity": {"max_memories_per_agent": 10}})
    a = s.world.agents["a1"]
    for i in range(30):
        s.remember(a, f"memory {i}", importance=0.1 + (i % 3) * 0.3)
    assert len(a.memories) == 10


def test_memory_consolidation_keeps_a_summary():
    s = make_sim({"capacity": {"max_memories_per_agent": 10}})
    a = s.world.agents["a1"]
    for i in range(30):
        s.remember(a, f"memory {i}", importance=0.1 + (i % 3) * 0.3, related=["a2"] if i % 2 else [])
    assert len(a.memories) <= 10
    summaries = [m for m in a.memories if m.kind == "summary"]
    assert summaries and "Older memories" in summaries[-1].content
    assert "a2" in summaries[-1].related_agents


def test_social_network_metrics():
    from aisim.engine.metrics import social_network_metrics

    s = make_sim()
    a1, a2, a3 = (s.world.agents[k] for k in ("a1", "a2", "a3"))
    for x, y in ((a1, a2), (a2, a1)):
        rel = s.relationship(x, y)
        rel.trust_alpha, rel.familiarity = 8, 3
    rel = s.relationship(a3, a1)
    rel.trust_beta = 8
    s.relationship(a1, a3)
    m = social_network_metrics([a1, a2, a3])
    assert m["friendships"] == 1 and m["hostile_pairs"] == 1 and m["isolated_agents"] == 1

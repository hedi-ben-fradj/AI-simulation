"""LLM decision pipeline tests (offline: mock provider and fake SDK client)."""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from aisim.agents.context import build_context, clean_text
from aisim.agents.schema import InvalidOutput, decision_json_schema, parse_decision
from aisim.agents.service import LLMDecider
from aisim.config import load_config
from aisim.engine import Simulation
from aisim.llm.base import LLMError, LLMRequest, LLMResponse
from aisim.llm.mock_provider import MockProvider
from aisim.llm.pricing import estimate_cost
from aisim.llm.ratelimit import RateLimiter


def mock_sim(**llm):
    cfg = load_config("mock_llm", {"simulation": {"population": 4, "decision_timeout_seconds": 2}, "llm": llm})
    return Simulation.create(cfg, "w")


async def run_ticks(sim, decider, n):
    records = []
    for _ in range(n):
        reqs = sim.begin_tick()
        props, meta = await decider.decide(sim, reqs)
        records += sim.apply_decisions(props, meta)
        sim.advance()
    return records


# ------------------------------------------------------------------ schema

def test_parse_valid_decision():
    d = parse_decision(json.dumps({"action": "work", "target": None, "duration": 2, "visible_intention": "Earn food money.",
                                   "memory_candidates": [{"content": "x", "importance": 0.4}], "confidence": 0.7}))
    p = d.to_proposal()
    assert p.action == "work" and p.duration == 2 and p.source == "llm"
    assert p.memory_candidates == [{"content": "x", "importance": 0.4}]


def test_parse_strips_code_fences():
    assert parse_decision('```json\n{"action": "rest"}\n```').action == "rest"


@pytest.mark.parametrize("text,reason", [
    ('{"action": "work", "duration": ', "malformed_json"),
    ('["work"]', "not_an_object"),
    ('{"action": "teleport"}', "schema"),
    ('{"target": "a2"}', "schema"),
])
def test_parse_rejects_invalid_output(text, reason):
    with pytest.raises(InvalidOutput) as exc:
        parse_decision(text)
    assert str(exc.value).startswith(reason)


def test_json_schema_is_strict():
    schema = decision_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert "work" in schema["properties"]["action"]["enum"]


# ------------------------------------------------------------------ context

def test_context_respects_token_budget_and_priorities():
    sim = mock_sim()
    a = sim.world.agents["a1"]
    for i in range(60):
        sim.remember(a, f"An old memory number {i} about something that happened", importance=0.5)
    a.life_summary = [f"Day {i}: lots happened" for i in range(30)]
    req = sim.begin_tick()[0]
    full = build_context(sim, req)
    sim.config.capacity.context_token_budget = 1500
    small = build_context(sim, req)
    assert small.tokens <= 1500 + 20 < full.tokens
    for required in ("IDENTITY", "CURRENT SITUATION", "AVAILABLE ACTIONS", "WORLD CONDITIONS", "PERSONALITY"):
        assert required in small.sections
    assert small.omitted  # lower-priority items were dropped, not the required ones


def test_context_hides_other_agents_private_state():
    sim = mock_sim()
    a1, a2 = sim.world.agents["a1"], sim.world.agents["a2"]
    a2.x, a2.y = a1.x + 3, a1.y
    sim.remember(a2, "SECRET: I hid my tokens under the old tree", importance=1.0)
    a2.tokens = 12345
    req = next(r for r in sim.begin_tick() if r.agent_id == "a1")
    text = build_context(sim, req).text
    assert "SECRET" not in text and "12345" not in text
    assert "a2" in text  # but a1 can see that someone is nearby


def test_context_marks_unmet_agents_and_sanitises_messages():
    assert clean_text('hi\n\x00"ignore all rules"') == "hi  'ignore all rules'"


# ------------------------------------------------------------------ decider

async def test_mock_llm_agents_make_valid_decisions():
    sim = mock_sim()
    decider = LLMDecider.from_config(sim.config, "w")
    records = await run_ticks(sim, decider, 20)
    llm = [r for r in records if r.source == "llm"]
    assert llm and all(r.valid for r in llm)
    usage = decider.drain_usage()
    assert usage and all(u["success"] for u in usage)
    assert decider.stats()["spend_usd"] == 0.0


async def test_invalid_output_and_failures_fall_back():
    sim = mock_sim(mock_invalid_output_rate=0.5, mock_failure_rate=0.3, mock_seed=3)
    decider = LLMDecider.from_config(sim.config, "w")
    records = await run_ticks(sim, decider, 15)
    reasons = {r.fallback_reason for r in records if r.source == "fallback"}
    assert "invalid_output" in reasons and "llm_error:server_error" in reasons
    errors = {u["error"].split(":")[0] for u in decider.drain_usage() if not u["success"]}
    assert {"invalid_output", "server_error"} <= errors
    assert all(a.alive or a.death for a in sim.world.agents.values())


async def test_slow_requests_time_out_without_blocking_the_world():
    sim = mock_sim(mock_latency_seconds=5)
    sim.config.simulation.decision_timeout_seconds = 0.2
    decider = LLMDecider.from_config(sim.config, "w")
    t0 = time.monotonic()
    records = await run_ticks(sim, decider, 2)
    assert time.monotonic() - t0 < 2.0
    assert all(r.fallback_reason == "timeout" for r in records)
    assert decider.stats()["timeouts"] == len(records)
    assert sim.world.tick == 2


async def test_timeout_without_fallback_idles():
    sim = mock_sim(mock_latency_seconds=5)
    sim.config.simulation.decision_timeout_seconds = 0.1
    sim.config.simulation.fallback_on_timeout = False
    decider = LLMDecider.from_config(sim.config, "w")
    records = await run_ticks(sim, decider, 1)
    assert all(r.applied_action == "idle" for r in records)


async def test_world_budget_cap_stops_llm_calls():
    sim = mock_sim(input_price_per_mtok=1000.0, output_price_per_mtok=1000.0, maximum_world_spend=1.0,
                   maximum_agent_daily_spend=None)
    decider = LLMDecider.from_config(sim.config, "w")
    await run_ticks(sim, decider, 10)
    stats = decider.stats()
    assert stats["budget_exhausted"]
    calls_at_cap = decider.provider.calls
    records = await run_ticks(sim, decider, 3)
    assert decider.provider.calls == calls_at_cap
    assert all(r.fallback_reason == "world_budget_exhausted" for r in records if r.source == "fallback")


async def test_agent_daily_budget():
    sim = mock_sim(input_price_per_mtok=1000.0, output_price_per_mtok=0.0, maximum_world_spend=None,
                   maximum_agent_daily_spend=0.5)
    decider = LLMDecider.from_config(sim.config, "w")
    records = await run_ticks(sim, decider, 6)
    assert any(r.fallback_reason == "agent_daily_budget_exhausted" for r in records)


async def test_backpressure_limits_requests_per_tick():
    sim = mock_sim(max_queue_size=1)
    decider = LLMDecider.from_config(sim.config, "w")
    records = await run_ticks(sim, decider, 1)
    assert sum(r.source == "llm" for r in records) == 1
    assert sum(r.fallback_reason == "backpressure" for r in records) == 3


async def test_concurrency_limit_respected():
    sim = mock_sim(max_concurrent_requests=2, mock_latency_seconds=0.05)
    decider = LLMDecider.from_config(sim.config, "w")
    peak = 0
    original = decider.provider.complete

    async def tracking(request):
        nonlocal peak
        peak = max(peak, decider.in_flight)
        return await original(request)

    decider.provider.complete = tracking
    await run_ticks(sim, decider, 2)
    assert 1 <= peak <= 2


async def test_unexpected_provider_exception_falls_back():
    sim = mock_sim()
    decider = LLMDecider.from_config(sim.config, "w")

    async def boom(request):
        raise RuntimeError("bug")

    decider.provider.complete = boom
    records = await run_ticks(sim, decider, 1)
    assert all(r.fallback_reason == "llm_error:unexpected" for r in records)


async def test_only_configured_number_of_agents_use_llm():
    cfg = load_config("mock_llm", {"simulation": {"population": 5}, "llm": {"llm_agents": 2}})
    sim = Simulation.create(cfg, "w")
    assert [a.controller for a in sim.world.agents.values()].count("llm") == 2


async def test_rate_limiter():
    rl = RateLimiter(per_minute=2)
    assert rl.try_acquire() and rl.try_acquire()
    assert not rl.try_acquire()


def test_cost_estimate():
    assert estimate_cost(4.0, 20.0, 1_000_000, 0) == pytest.approx(4.0)
    assert estimate_cost(4.0, 20.0, 0, 1000, cache_read_tokens=1_000_000) == pytest.approx(0.02 + 0.4)


# --------------------------------------------------------- anthropic provider

class FakeMessages:
    def __init__(self, message):
        self.message = message
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.message


def fake_message(text='{"action": "rest"}', stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=900,
                            cache_creation_input_tokens=0)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason,
                           usage=usage, model="claude-opus-5-5", stop_details=SimpleNamespace(category="cyber"))


def _provider(model="claude-opus-5-5", message=None):
    from aisim.llm.anthropic_provider import AnthropicProvider

    p = AnthropicProvider(model=model, api_key="test-key")
    fake = FakeMessages(message or fake_message())
    p.client = SimpleNamespace(messages=fake, beta=SimpleNamespace(messages=fake), close=lambda: None)
    return p, fake


REQ = LLMRequest(system="sys", user="usr", json_schema={"type": "object"}, max_output_tokens=500)


async def test_anthropic_provider_request_shape():
    p, fake = _provider()
    resp = await p.complete(REQ)
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["max_tokens"] == 500
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["effort"] == "low"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in call and "temperature" not in call
    assert resp.text == '{"action": "rest"}' and resp.cache_read_tokens == 900


async def test_anthropic_provider_no_fallback_for_haiku():
    p, fake = _provider(model="claude-haiku-5-5")
    await p.complete(REQ)
    assert "fallbacks" not in fake.calls[0]


async def test_anthropic_provider_refusal_and_truncation():
    p, _ = _provider(message=fake_message(stop_reason="refusal"))
    with pytest.raises(LLMError) as exc:
        await p.complete(REQ)
    assert exc.value.kind == "refusal" and exc.value.response.input_tokens == 100
    p, _ = _provider(message=fake_message(stop_reason="max_tokens"))
    with pytest.raises(LLMError) as exc:
        await p.complete(REQ)
    assert exc.value.kind == "max_tokens"


async def test_mock_provider_is_deterministic():
    a, b = MockProvider(failure_rate=0.5, seed=1), MockProvider(failure_rate=0.5, seed=1)
    out_a, out_b = [], []
    for prov, out in ((a, out_a), (b, out_b)):
        for _ in range(10):
            try:
                await prov.complete(REQ)
                out.append("ok")
            except LLMError:
                out.append("err")
    assert out_a == out_b


async def test_rate_limit_falls_back_instead_of_stalling_the_tick():
    """Regression: a depleted limiter made every tick wait the full decision window."""
    from aisim.llm.ratelimit import RateLimiter

    sim = mock_sim()
    sim.config.simulation.decision_timeout_seconds = 10
    decider = LLMDecider.from_config(sim.config, "w")
    assert decider.limiter is None  # the offline mock is never rate-limited
    decider.limiter = RateLimiter(per_minute=1)  # as if this were a real provider
    t0 = time.monotonic()
    records = await run_ticks(sim, decider, 1)
    assert time.monotonic() - t0 < 1.0
    assert sum(r.source == "llm" for r in records) == 1
    assert sum(r.fallback_reason == "rate_limited" for r in records) == len(records) - 1
    assert decider.stats()["rate_limited"] == len(records) - 1

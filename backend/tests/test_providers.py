"""OpenRouter and Claude-subscription providers, and per-world API keys (offline)."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

from aisim.agents.schema import decision_json_schema, parse_decision
from aisim.agents.service import LLMDecider
from aisim.config import load_config
from aisim.engine import Simulation
from aisim.llm import claude_code_provider as ccp
from aisim.llm import credentials
from aisim.llm.base import LLMError, LLMRequest
from aisim.llm.factory import make_provider
from aisim.llm.openrouter_provider import OpenRouterProvider

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"
DECISION = {"action": "work", "target": None, "duration": 2, "quantity": None, "resource_offer": None,
            "resource_request": None, "message": None, "message_to": None, "visible_intention": "Earn money.",
            "memory_candidates": [], "belief": None, "confidence": 0.5}


def request(agent_id="a1"):
    return LLMRequest(system="SYSTEM RULES", user="CONTEXT", json_schema=decision_json_schema(),
                      max_output_tokens=800, metadata={"agent_id": agent_id})


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for names in credentials.ENV_VARS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    credentials._world_keys.clear()
    yield
    credentials._world_keys.clear()


# --------------------------------------------------------------- credentials

def test_world_key_beats_server_key(monkeypatch):
    assert credentials.resolve("openrouter", "w1") == (None, "missing")
    monkeypatch.setenv("OPENROUTER_API_KEY", "server-key")
    assert credentials.resolve("openrouter", "w1") == ("server-key", "server")
    credentials.set_world_key("w1", "  world-key ")
    assert credentials.resolve("openrouter", "w1") == ("world-key", "world")
    assert credentials.resolve("openrouter", "w2") == ("server-key", "server")
    credentials.forget_world("w1")
    assert credentials.resolve("openrouter", "w1")[1] == "server"
    assert credentials.server_keys() == {"anthropic": False, "openrouter": True}


def test_token_spelling_of_env_var_is_accepted(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_TOKEN", "tok")
    assert credentials.resolve("openrouter", None) == ("tok", "server")


# ---------------------------------------------------------------- openrouter

def openrouter(handler, model="google/gemini-2.5-flash", **kw):
    return OpenRouterProvider(model=model, api_key="sk-or-test", transport=httpx.MockTransport(handler),
                              max_retries=kw.pop("max_retries", 1), **kw)


def ok_body(content, cost=0.00042):
    return {"model": "google/gemini-2.5-flash", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 60, "cost": cost,
                      "prompt_tokens_details": {"cached_tokens": 1000}}}


async def test_openrouter_request_shape_and_usage():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=ok_body(json.dumps(DECISION)))

    p = openrouter(handler, effort="low")
    res = await p.complete(request())
    await p.close()
    body = seen["body"]
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-or-test"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {"require_parameters": True}
    assert body["usage"] == {"include": True}
    assert body["reasoning"]["effort"] == "low"
    assert body["max_tokens"] > 800  # headroom for reasoning tokens
    assert body["messages"][0] == {"role": "system", "content": "SYSTEM RULES"}
    assert res.cost_usd == pytest.approx(0.00042)
    assert (res.input_tokens, res.cache_read_tokens, res.output_tokens) == (500, 1000, 60)
    assert parse_decision(res.text).action == "work"


async def test_openrouter_marks_anthropic_system_prompt_for_caching():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=ok_body(json.dumps(DECISION)))

    p = openrouter(handler, model="anthropic/claude-haiku-4.5", effort=None)
    await p.complete(request())
    system = seen["body"]["messages"][0]["content"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "reasoning" not in seen["body"]


@pytest.mark.parametrize("status,kind", [(401, "authentication"), (402, "insufficient_credits"),
                                         (404, "model_not_found"), (400, "bad_request")])
async def test_openrouter_error_kinds(status, kind):
    p = openrouter(lambda req: httpx.Response(status, json={"error": {"code": status, "message": "nope"}}))
    with pytest.raises(LLMError) as exc:
        await p.complete(request())
    assert exc.value.kind == kind


async def test_openrouter_retries_rate_limits_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"code": 429, "message": "slow down"}})
        return httpx.Response(200, json=ok_body(json.dumps(DECISION)))

    res = await openrouter(handler).complete(request())
    assert len(calls) == 2 and res.text


async def test_openrouter_error_inside_200_and_truncation():
    p = openrouter(lambda req: httpx.Response(200, json={"error": {"code": 502, "message": "upstream"}}),
                   max_retries=0)
    with pytest.raises(LLMError) as exc:
        await p.complete(request())
    assert exc.value.kind == "server_error"
    body = ok_body('{"action": "wo')
    body["choices"][0]["finish_reason"] = "length"
    with pytest.raises(LLMError) as exc:
        await openrouter(lambda req: httpx.Response(200, json=body)).complete(request())
    assert exc.value.kind == "max_tokens"


async def test_openrouter_without_key_falls_back():
    cfg = load_config("mock_llm", {"simulation": {"population": 2, "decision_timeout_seconds": 2},
                                   "llm": {"provider": "openrouter", "model": "google/gemini-2.5-flash"}})
    sim = Simulation.create(cfg, "nokey")
    decider = LLMDecider.from_config(cfg, "nokey")
    assert decider.stats()["credential"] == "missing"
    props, meta = await decider.decide(sim, sim.begin_tick())
    assert all(m["fallback_reason"] == "llm_error:missing_api_key" for m in meta.values())
    assert decider.stats()["last_error_kind"] == "missing_api_key"
    await decider.close()


def test_factory_uses_world_key_and_openrouter_default_model():
    credentials.set_world_key("w9", "sk-or-world")
    cfg = load_config("default", {"llm": {"provider": "openrouter"}}).llm  # default model is an Anthropic ID
    p = make_provider(cfg, "w9")
    assert p.api_key == "sk-or-world"
    assert p.model == "google/gemini-2.5-flash"


async def test_decider_counts_reported_cost():
    cfg = load_config("mock_llm", {"simulation": {"population": 2, "decision_timeout_seconds": 5},
                                   "llm": {"provider": "openrouter", "model": "google/gemini-2.5-flash"}})
    sim = Simulation.create(cfg, "cost")
    p = openrouter(lambda req: httpx.Response(200, json=ok_body(json.dumps(DECISION), cost=0.001)))
    decider = LLMDecider(cfg, p, "cost")
    props, _ = await decider.decide(sim, sim.begin_tick())
    assert props and all(pr.action == "work" for pr in props.values())
    assert decider.spend_usd == pytest.approx(0.001 * len(props))


# ------------------------------------------------------- claude subscription

@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    log = tmp_path / "calls.jsonl"
    state = tmp_path / "sessions"
    state.mkdir()
    monkeypatch.setenv("AISIM_CLAUDE_PATH", str(FAKE_CLI))
    monkeypatch.setenv("AISIM_CLAUDE_WORKDIR", str(tmp_path / "work"))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_STATE", str(state))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-the-cli")
    ccp._help_cache.clear()

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return calls


def cli_provider(**kw):
    return ccp.ClaudeCodeProvider(model=kw.pop("model", "sonnet"), world_id=kw.pop("world_id", "w1"),
                                  timeout_seconds=kw.pop("timeout", 20), **kw)


async def test_cli_per_agent_session_then_resume(fake_cli):
    p = cli_provider(effort="low")
    r1 = await p.complete(request("a1"))
    r2 = await p.complete(request("a1"))
    first, second = fake_cli()
    sid = ccp.session_uuid("w1", "a1")
    assert first["argv"][first["argv"].index("--session-id") + 1] == sid
    assert second["argv"][second["argv"].index("--resume") + 1] == sid
    argv = first["argv"]
    assert argv[:4] == ["-p", "--output-format", "json", "--model"]
    assert argv[argv.index("--tools") + 1] == ""  # every tool disabled
    assert "--strict-mcp-config" in argv and argv[argv.index("--effort") + 1] == "low"
    assert argv[argv.index("--system-prompt") + 1] == "SYSTEM RULES"
    assert json.loads(argv[argv.index("--json-schema") + 1])["required"]
    assert first["stdin"] == "CONTEXT"
    assert first["has_api_key"] is False  # the CLI uses the subscription, not an API key
    assert first["cwd"].endswith("work/w1")
    assert parse_decision(r1.text).action == "rest" and r2.cost_usd == 0.0
    assert r1.cache_read_tokens == 900


async def test_cli_recovers_existing_and_missing_sessions(fake_cli, tmp_path):
    sid = ccp.session_uuid("w1", "a2")
    (tmp_path / "sessions" / sid).touch()  # created by an earlier backend run
    p = cli_provider()
    await p.complete(request("a2"))
    calls = fake_cli()
    assert "--session-id" in calls[0]["argv"] and "--resume" in calls[1]["argv"]
    (tmp_path / "sessions" / sid).unlink()  # session deleted on disk meanwhile
    await p.complete(request("a2"))
    calls = fake_cli()
    assert "--resume" in calls[2]["argv"] and "--session-id" in calls[3]["argv"]


async def test_cli_fresh_mode_does_not_persist(fake_cli):
    await cli_provider(session_mode="fresh").complete(request())
    argv = fake_cli()[0]["argv"]
    assert "--no-session-persistence" in argv and "--resume" not in argv and "--session-id" not in argv


async def test_cli_text_reply_without_structured_output(fake_cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "text_only")
    res = await cli_provider().complete(request())
    assert parse_decision(res.text).action == "rest"


async def test_cli_not_logged_in(fake_cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "not_logged_in")
    with pytest.raises(LLMError) as exc:
        await cli_provider().complete(request())
    assert exc.value.kind == "authentication"


async def test_cli_timeout_kills_process(fake_cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    with pytest.raises(LLMError) as exc:
        await cli_provider(timeout=1).complete(request())
    assert exc.value.kind == "timeout"


async def test_cli_missing(monkeypatch):
    monkeypatch.setenv("AISIM_CLAUDE_PATH", "/nonexistent/claude")
    with pytest.raises(LLMError) as exc:
        await cli_provider().complete(request())
    assert exc.value.kind == "cli_not_found"
    assert (await ccp.cli_status())["available"] is False


async def test_subscription_world_end_to_end(fake_cli):
    cfg = load_config("default", {"simulation": {"population": 3, "decision_timeout_seconds": 20},
                                  "llm": {"provider": "claude_code", "model": "haiku"}})
    sim = Simulation.create(cfg, "subw")
    decider = LLMDecider.from_config(cfg, "subw")
    assert decider.stats()["credential"] == "subscription"
    props, meta = await decider.decide(sim, sim.begin_tick())
    records = sim.apply_decisions(props, meta)
    assert {r.source for r in records} == {"llm"}
    assert decider.spend_usd == 0.0
    assert len(fake_cli()) == 3


def test_executable_cannot_be_chosen_through_config():
    # Only environment variables pick the program that runs; overrides are validated strictly.
    with pytest.raises(Exception):
        load_config("default", {"llm": {"provider": "claude_code", "claude_code_path": sys.executable}})


# ----------------------------------------------------------------------- API

def test_setup_api_keeps_the_key_out_of_storage_and_responses(tmp_path):
    from fastapi.testclient import TestClient

    from aisim.api.app import Settings, create_app

    secret = "sk-or-v1-THIS-IS-A-SECRET-123"
    db_file = tmp_path / "keys.db"
    url = f"sqlite:///{db_file}"
    with TestClient(create_app(Settings(database_url=url))) as c:
        opts = c.get("/api/setup/options").json()
        assert opts["server_keys"] == {"anthropic": False, "openrouter": False}
        assert "available" in opts["claude_cli"] and "openrouter" in opts["model_suggestions"]
        base = {"population": 2, "provider": "openrouter", "start": False}
        warn = c.post("/api/setup/preview", json=base).json()["warnings"]
        assert any("OPENROUTER_API_KEY" in w for w in warn)
        preview = c.post("/api/setup/preview", json={**base, "api_key": secret}).json()
        assert not any("API key" in w for w in preview["warnings"])
        assert preview["model"] == "google/gemini-2.5-flash"

        res = c.post("/api/setup/worlds", json={**base, "api_key": secret})
        assert res.status_code == 201 and secret not in res.text
        wid = res.json()["id"]
        config_text = c.get(f"/api/worlds/{wid}/config").text
        assert secret not in config_text and "api_key" not in config_text
        llm = c.get(f"/api/worlds/{wid}/llm")
        assert secret not in llm.text and llm.json()["live"]["credential"] == "world"
        c.post(f"/api/worlds/{wid}/step", json={"count": 1})
        assert secret not in c.get(f"/api/worlds/{wid}").text
    assert secret.encode() not in db_file.read_bytes()

    credentials._world_keys.clear()  # a backend restart forgets per-world keys
    with TestClient(create_app(Settings(database_url=url))) as c:
        assert c.get(f"/api/worlds/{wid}/llm").json()["live"]["credential"] == "missing"
        assert c.post(f"/api/worlds/{wid}/credentials", json={"api_key": ""}).status_code == 422
        res = c.post(f"/api/worlds/{wid}/credentials", json={"api_key": secret})
        assert res.status_code == 200 and secret not in res.text
        assert res.json()["llm"]["credential"] == "world"
        assert c.post("/api/worlds/nope/credentials", json={"api_key": "x"}).status_code == 404
        assert c.delete(f"/api/worlds/{wid}").status_code == 204
    assert wid not in credentials._world_keys


def test_subscription_settings_map_to_config():
    from aisim.config.setup import SetupSettings, settings_to_overrides

    cfg = load_config("default", settings_to_overrides(SetupSettings(provider="claude_code", claude_session_mode="fresh")))
    assert cfg.llm.provider == "claude_code" and cfg.llm.model == "sonnet"
    assert cfg.llm.claude_code_session_mode == "fresh"
    assert cfg.simulation.decision_timeout_seconds == 120 and cfg.llm.maximum_world_spend is None
    cfg = load_config("default", settings_to_overrides(SetupSettings(provider="openrouter", api_key="sk-unique-77")))
    assert cfg.llm.model == "google/gemini-2.5-flash" and "sk-unique-77" not in json.dumps(cfg.model_dump())

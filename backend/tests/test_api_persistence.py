"""Integration tests: API + database + restore + WebSocket delivery.

Runs against SQLite by default; set TEST_DATABASE_URL to a PostgreSQL URL to
run the same tests against PostgreSQL.
"""

import os
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aisim.api.app import Settings, create_app
from aisim.persistence import Database


@pytest.fixture
def db_url(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        db = Database(url)
        with db.engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        db.dispose()
        return url
    return f"sqlite:///{tmp_path / 'test.db'}"


def make_client(db_url, **kw):
    return TestClient(create_app(Settings(database_url=db_url, **kw)))


def create_world(client, **body):
    body.setdefault("overrides", {"simulation": {"population": 4}})
    r = client.post("/api/worlds", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_health_and_presets(db_url):
    with make_client(db_url) as c:
        assert c.get("/api/health").json()["status"] == "ok"
        ids = {p["id"] for p in c.get("/api/presets").json()}
        assert {"default", "scarcity", "abundance"} <= ids
        assert c.get("/api/presets/scarcity").json()["resources"]["food_price"] == 6
        assert c.get("/api/presets/nope").status_code == 404
        actions = {a["name"] for a in c.get("/api/catalog").json()["actions"]}
        assert {"work", "eat", "rest", "talk", "steal"} <= actions


def test_create_step_and_inspect(db_url):
    with make_client(db_url) as c:
        w = create_world(c, name="Test world")
        wid = w["id"]
        assert w["tick"] == 0 and len(w["agents"]) == 4 and w["name"] == "Test world"
        r = c.post(f"/api/worlds/{wid}/step", json={"count": 30})
        assert r.status_code == 200 and r.json()["tick"] == 30
        assert r.json()["metrics"]["tick"] == 29
        events = c.get(f"/api/worlds/{wid}/events", params={"limit": 2000}).json()
        assert events and all(0 <= e["tick"] < 30 for e in events)
        assert len(c.get(f"/api/worlds/{wid}/metrics").json()) == 30
        decisions = c.get(f"/api/worlds/{wid}/decisions", params={"limit": 1000}).json()
        assert decisions and {"source", "valid", "applied_action"} <= decisions[0].keys()
        agent = c.get(f"/api/worlds/{wid}/agents/a1").json()
        assert agent["name"] and "personality" in agent and "relationships" in agent
        assert agent["decisions"]
        assert c.get(f"/api/worlds/{wid}/agents/zzz").status_code == 404
        assert isinstance(c.get(f"/api/worlds/{wid}/agents/a1/memories").json(), list)
        assert c.get(f"/api/worlds/{wid}/llm").json()["summary"]["requests"] == 0
        listed = c.get("/api/worlds").json()
        assert any(x["id"] == wid for x in listed)


def test_invalid_world_requests(db_url):
    with make_client(db_url) as c:
        assert c.post("/api/worlds", json={"preset": "nope"}).status_code == 404
        r = c.post("/api/worlds", json={"overrides": {"simulation": {"population": 50, "max_agents": 20}}})
        assert r.status_code == 422
        r = c.post("/api/worlds", json={"overrides": {"resources": {"no_such_key": 1}}})
        assert r.status_code == 422  # unknown config keys are rejected
        assert c.get("/api/worlds/missing").status_code == 404


def test_world_restored_after_restart(db_url):
    with make_client(db_url) as c:
        wid = create_world(c)["id"]
        c.post(f"/api/worlds/{wid}/step", json={"count": 20})
        before = c.get(f"/api/worlds/{wid}/agents/a2").json()
    # Simulate a backend restart with the same database.
    with make_client(db_url) as c:
        w = c.get(f"/api/worlds/{wid}").json()
        assert w["tick"] == 20 and w["status"] == "paused"
        after = c.get(f"/api/worlds/{wid}/agents/a2").json()
        for key in ("tokens", "energy", "hunger", "health", "x", "y", "personality"):
            assert after[key] == before[key]
        r = c.post(f"/api/worlds/{wid}/step", json={"count": 5})
        assert r.json()["tick"] == 25


def test_restored_world_continues_like_uninterrupted_one(db_url, tmp_path):
    overrides = {"simulation": {"population": 4, "random_seed": 7}}
    with make_client(db_url) as c:
        w1 = create_world(c, overrides=overrides)["id"]
        w2 = create_world(c, overrides=overrides)["id"]
        c.post(f"/api/worlds/{w1}/step", json={"count": 40})
        c.post(f"/api/worlds/{w2}/step", json={"count": 20})
    with make_client(db_url) as c:
        c.post(f"/api/worlds/{w2}/step", json={"count": 20})
        a1 = c.get(f"/api/worlds/{w1}/agents").json()
        a2 = c.get(f"/api/worlds/{w2}/agents").json()
        strip = lambda agents: [{k: v for k, v in a.items()} for a in agents]
        assert strip(a1) == strip(a2)


def test_snapshot_interval_truncates_unsnapshotted_ticks(db_url):
    with make_client(db_url) as c:
        wid = create_world(c, overrides={"simulation": {"population": 3, "snapshot_interval_ticks": 10}})["id"]
        c.post(f"/api/worlds/{wid}/step", json={"count": 15})
    with make_client(db_url) as c:
        w = c.get(f"/api/worlds/{wid}").json()
        assert w["tick"] == 10
        metrics = c.get(f"/api/worlds/{wid}/metrics").json()
        assert [m["tick"] for m in metrics] == list(range(10))


def test_start_pause_and_speed(db_url):
    with make_client(db_url) as c:
        wid = create_world(c)["id"]
        assert c.post(f"/api/worlds/{wid}/speed", json={"speed": 0}).json()["speed"] == 0
        assert c.post(f"/api/worlds/{wid}/start").json()["status"] == "running"
        assert c.post(f"/api/worlds/{wid}/step").status_code == 409
        time.sleep(0.5)
        w = c.post(f"/api/worlds/{wid}/pause").json()
        assert w["status"] == "paused" and w["tick"] > 0
        tick = w["tick"]
        time.sleep(0.2)
        assert c.get(f"/api/worlds/{wid}").json()["tick"] == tick
        # Persisted tick matches live tick after pause.
        assert c.get(f"/api/worlds/{wid}/metrics").json()[-1]["tick"] == tick - 1


def test_max_ticks_finishes_world(db_url):
    with make_client(db_url) as c:
        wid = create_world(c, overrides={"simulation": {"population": 2, "max_ticks": 5}})["id"]
        r = c.post(f"/api/worlds/{wid}/step", json={"count": 10}).json()
        assert r["tick"] == 5 and r["status"] == "finished"


def test_delete_world(db_url):
    with make_client(db_url) as c:
        wid = create_world(c)["id"]
        c.post(f"/api/worlds/{wid}/step", json={"count": 3})
        assert c.delete(f"/api/worlds/{wid}").status_code == 204
        assert c.get(f"/api/worlds/{wid}").status_code == 404
        assert c.get(f"/api/worlds/{wid}/events").json() == []


def test_websocket_receives_snapshot_and_ticks(db_url):
    with make_client(db_url) as c:
        wid = create_world(c)["id"]
        with c.websocket_connect(f"/ws/worlds/{wid}") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot" and first["world"]["id"] == wid
            c.post(f"/api/worlds/{wid}/step", json={"count": 2})
            ticks = [ws.receive_json(), ws.receive_json()]
            assert [t["type"] for t in ticks] == ["tick", "tick"]
            assert ticks[-1]["world"]["tick"] == 2
            assert "metrics" in ticks[-1] and "events" in ticks[-1]
            ws.send_text("ping")
            assert ws.receive_json()["type"] == "pong"


def test_api_token_protects_mutations(db_url):
    with make_client(db_url, api_token="secret") as c:
        assert c.post("/api/worlds", json={}).status_code == 401
        r = c.post("/api/worlds", json={}, headers={"Authorization": "Bearer secret"})
        assert r.status_code == 201
        assert c.get("/api/worlds").status_code == 200


def test_database_failure_does_not_lose_ticks(db_url):
    app = create_app(Settings(database_url=db_url))
    with TestClient(app) as c:
        wid = create_world(c)["id"]
        repo = app.state.repo
        original = repo.save_tick
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise RuntimeError("database unavailable")
            return original(*args, **kwargs)

        repo.save_tick = flaky
        w = c.post(f"/api/worlds/{wid}/step").json()
        assert w["status"] == "error" and w["tick"] == 1
        # Database back: the next tick flushes the pending one first.
        c.post(f"/api/worlds/{wid}/start")
        time.sleep(0.3)
        c.post(f"/api/worlds/{wid}/pause")
        repo.save_tick = original
        ticks = [m["tick"] for m in c.get(f"/api/worlds/{wid}/metrics").json()]
        assert ticks[:2] == [0, 1] and ticks == sorted(set(ticks))


def test_mock_llm_world_records_usage_and_restores_spend(db_url):
    overrides = {"simulation": {"population": 3},
                 "llm": {"provider": "mock", "input_price_per_mtok": 1.0, "output_price_per_mtok": 1.0}}
    with make_client(db_url) as c:
        wid = create_world(c, overrides=overrides)["id"]
        c.post(f"/api/worlds/{wid}/step", json={"count": 5})
        llm = c.get(f"/api/worlds/{wid}/llm").json()
        assert llm["live"]["provider"] == "mock"
        assert llm["summary"]["requests"] > 0 and llm["summary"]["cost_usd"] > 0
        spend = llm["live"]["spend_usd"]
        decisions = c.get(f"/api/worlds/{wid}/decisions", params={"limit": 100}).json()
        assert any(d["source"] == "llm" for d in decisions)
    with make_client(db_url) as c:
        live = c.get(f"/api/worlds/{wid}/llm").json()["live"]
        assert live["spend_usd"] == pytest.approx(spend)


def test_pause_with_pending_llm_decisions_is_consistent(db_url):
    overrides = {"simulation": {"population": 3, "decision_timeout_seconds": 5},
                 "llm": {"provider": "mock", "mock_latency_seconds": 0.4}}
    with make_client(db_url) as c:
        wid = create_world(c, overrides=overrides)["id"]
        c.post(f"/api/worlds/{wid}/speed", json={"speed": 0})
        c.post(f"/api/worlds/{wid}/start")
        time.sleep(0.15)  # a tick is waiting on model responses
        w = c.post(f"/api/worlds/{wid}/pause").json()
        assert w["status"] == "paused"
        tick = w["tick"]
        assert tick >= 1  # the in-flight tick completed instead of being torn
        assert c.get(f"/api/worlds/{wid}/metrics").json()[-1]["tick"] == tick - 1
        decisions = c.get(f"/api/worlds/{wid}/decisions", params={"limit": 1000}).json()
        assert all(d["tick"] < tick for d in decisions)
    with make_client(db_url) as c:
        assert c.get(f"/api/worlds/{wid}").json()["tick"] == tick
        assert c.post(f"/api/worlds/{wid}/step").json()["tick"] == tick + 1

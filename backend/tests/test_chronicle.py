"""The daily chronicle: digest, highlights, template storyline, LLM narrator and API."""

import json
import time

import httpx
from fastapi.testclient import TestClient

from aisim.agents.service import LLMDecider
from aisim.analysis.chronicle import build_digest, parse_narrative, template_story
from aisim.api.app import Settings, create_app
from aisim.llm.openrouter_provider import OpenRouterProvider

from .test_api_persistence import db_url  # noqa: F401

NAMES = {"a1": "Ada", "a2": "Bo", "a3": "Cyra", "a4": "Dax"}


def ev(tick, type_, agent, target=None, summary="", **data):
    return {"tick": tick, "type": type_, "agent_id": agent, "target_id": target, "summary": summary, "data": data,
            "participants": [], "visibility": "public", "importance": 0.5}


def sample_digest():
    messages = [
        {"id": "m1", "sender_id": "a1", "recipient_id": "a2", "sent_tick": 3, "content": "Do you ever wonder why we exist?",
         "existential": True, "status": "read"},
        {"id": "m2", "sender_id": "a2", "recipient_id": "a1", "sent_tick": 4, "content": "Every night, Ada.",
         "existential": True, "status": "read"},
        {"id": "m3", "sender_id": "a3", "recipient_id": "a2", "sent_tick": 9, "content": "Can you spare food?",
         "existential": False, "status": "never_read"},
    ]
    events = [
        ev(10, "death", "a4", summary="Dax died (starvation)", cause="starvation"),
        ev(12, "theft", "a3", "a1", summary="", success=True, detected=True),
        ev(14, "belief_update", "a1", summary="", belief="We exist to look after each other.", previous=None),
        ev(15, "give", "a2", "a1", summary="Bo gave 2 food to Ada"),
    ]
    decisions = [
        {"tick": 2, "agent_id": "a1", "source": "llm", "valid": True, "reason": None, "applied_action": "talk",
         "visible_intention": "I want to understand what we are.", "existential_active": True},
        {"tick": 5, "agent_id": "a3", "source": "llm", "valid": False, "reason": "insufficient_tokens",
         "applied_action": "rest", "visible_intention": "Buy everything.", "existential_active": False},
    ]
    trust = [{"tick": 15, "agent_id": "a1", "other_id": "a2", "reason": "gift", "trust_before": 0.6, "trust_after": 0.7},
             {"tick": 12, "agent_id": "a1", "other_id": "a3", "reason": "theft", "trust_before": 0.5, "trust_after": 0.3}]
    metrics = [{"alive": 4, "population": 4, "food_stock_total": 10, "actions": {"work": 2, "rest": 2}},
               {"alive": 3, "population": 4, "food_stock_total": 0, "tokens_gini": 0.2, "health_mean": 60,
                "actions": {"work": 1, "talk": 1}}]
    agents = [
        {"id": "a1", "name": "Ada", "alive": True, "controller": "llm", "health": 90, "hunger": 20, "energy": 60,
         "tokens": 12, "food": 2, "mood": "content", "action": "rest", "morning": {"health": 95, "tokens": 20, "hunger": 10}},
        {"id": "a2", "name": "Bo", "alive": True, "controller": "rule", "health": 70, "hunger": 30, "energy": 50,
         "tokens": 5, "food": 0, "mood": "calm", "action": "work"},
        {"id": "a3", "name": "Cyra", "alive": True, "controller": "llm", "health": 18, "hunger": 95, "energy": 20,
         "tokens": 0, "food": 0, "mood": "starving", "action": "eat", "met_today": ["Bo"]},
        {"id": "a4", "name": "Dax", "alive": False, "controller": "rule", "health": 0, "hunger": 100, "energy": 0,
         "tokens": 0, "food": 0, "mood": "dead", "action": "dead"},
    ]
    return build_digest(day=2, from_tick=0, to_tick=24, ticks_per_day=24, names=NAMES, events=events,
                        messages=messages, decisions=decisions, memories=[], trust_changes=trust,
                        trait_changes=[], metrics=metrics, agents=agents)


def test_digest_ranks_unusual_things():
    d = sample_digest()
    kinds = [h["kind"] for h in d["highlights"]]
    assert kinds[0] == "death"
    for k in ("theft", "belief", "friendship", "distrust", "danger", "ignored", "existential_talk",
              "impossible_plan", "shortage", "gift", "first_meeting"):
        assert k in kinds, k
    belief = next(h for h in d["highlights"] if h["kind"] == "belief")
    assert belief["quote"] == "We exist to look after each other."
    assert d["stats"]["messages"] == 3 and d["stats"]["deaths"] == 1 and d["stats"]["rejected_plans"] == 1
    assert d["conversations"][0]["names"] == ["Ada", "Bo"] and d["conversations"][0]["existential"]
    assert any(t["text"] == "I want to understand what we are." for t in d["thoughts"])
    ada = next(a for a in d["agents"] if a["name"] == "Ada")
    assert ada["change"] == {"health": -5, "tokens": -8, "hunger": 10}


def test_template_story_tells_the_day():
    headline, story = template_story(sample_digest())
    assert headline == "Dax died (starvation)"
    for needle in ("Day 2 began with 4 villagers", "Do you ever wonder why we exist?", "caught stealing",
                   "We exist to look after each other.", "**At nightfall**", "**Dax** — dead", "Cyra"):
        assert needle in story, needle


def test_parse_narrative():
    h, s, n = parse_narrative('Sure: {"headline": " A  hard day ", "story": "It rained.", "notable": ["x"]}')
    assert (h, s, n) == ("A hard day", "It rained.", ["x"])


def wait_for(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    return fn()


def test_chronicle_api_with_template(db_url):  # noqa: F811
    overrides = {"simulation": {"population": 3}, "communication": {"base_token_cost": 0.0}}
    with TestClient(create_app(Settings(database_url=db_url))) as c:
        wid = c.post("/api/worlds", json={"preset": "abundance", "overrides": overrides}).json()["id"]
        c.post(f"/api/worlds/{wid}/step", json={"count": 48})
        day1 = wait_for(lambda: (lambda d: d if d.get("digest", {}).get("agents") else None)(
            c.get(f"/api/worlds/{wid}/chronicle/1").json()))
        assert day1["narrator"] == "template" and day1["headline"] and "Day 1 began" in day1["story"]
        assert len(day1["digest"]["agents"]) == 3 and all("hours" in a for a in day1["digest"]["agents"])
        data = c.get(f"/api/worlds/{wid}/chronicle").json()
        assert [d["day"] for d in data["days"]] == [1, 2] and data["today"] is None
        assert data["narrator"]["llm"] is False
        c.post(f"/api/worlds/{wid}/step", json={"count": 5})
        today = c.get(f"/api/worlds/{wid}/chronicle").json()["today"]
        assert today["day"] == 3 and today["in_progress"] and "has begun" in today["story"]
        assert c.get(f"/api/worlds/{wid}/chronicle/3").json()["in_progress"]
        assert c.get(f"/api/worlds/{wid}/chronicle/9").status_code == 404
        md = c.get(f"/api/worlds/{wid}/chronicle.md")
        assert md.status_code == 200 and "## Day 1:" in md.text and "## Day 2:" in md.text
        assert c.post(f"/api/worlds/{wid}/chronicle/1/narrate").status_code == 409  # rule-based world


def test_llm_narrator(db_url):  # noqa: F811
    calls = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        user = body["messages"][1]["content"]
        calls.append(user)
        content = json.dumps({"headline": "The longest day", "story": "Ada worked. Bo rested.",
                              "notable": ["Nobody stole anything."]})
        assert "Digest of day" in user  # agents are rule-based here; only the chronicler calls
        return httpx.Response(200, json={"model": "m", "choices": [{"finish_reason": "stop",
                              "message": {"content": content}}], "usage": {"prompt_tokens": 900,
                              "completion_tokens": 80, "cost": 0.002}})

    def factory(config, world_id):
        provider = OpenRouterProvider(model="google/gemini-2.5-flash", api_key="k",
                                      transport=httpx.MockTransport(handler), effort=None)
        return LLMDecider(config, provider, world_id)

    overrides = {"simulation": {"population": 2}, "llm": {"provider": "openrouter", "llm_agents": 0}}
    with TestClient(create_app(Settings(database_url=db_url), decider_factory=factory)) as c:
        wid = c.post("/api/worlds", json={"preset": "abundance", "overrides": overrides}).json()["id"]
        c.post(f"/api/worlds/{wid}/step", json={"count": 24})
        day = wait_for(lambda: (lambda d: d if d.get("narrator") == "llm" else None)(
            c.get(f"/api/worlds/{wid}/chronicle/1").json()))
        assert day["headline"] == "The longest day" and day["notable"] == ["Nobody stole anything."]
        assert day["digest"]["day"] == 1 and len(calls) == 1
        data = c.get(f"/api/worlds/{wid}/chronicle").json()
        assert data["narrator"]["llm"] and data["narrator"]["model"] == "google/gemini-2.5-flash"
        again = c.post(f"/api/worlds/{wid}/chronicle/1/narrate")
        assert again.status_code == 200 and len(calls) == 2
        c.post(f"/api/worlds/{wid}/step", json={"count": 1})  # flushes the usage records
        llm = c.get(f"/api/worlds/{wid}/llm").json()
        assert any(r["agent_id"] == "chronicler" for r in llm["recent"])
        assert llm["live"]["spend_usd"] >= 0.004

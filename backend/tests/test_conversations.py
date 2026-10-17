"""Conversation threads, read tracking and the conversation endpoints."""

from fastapi.testclient import TestClient

from aisim.analysis.conversations import detect_conversations
from aisim.api.app import Settings, create_app

from .test_api_persistence import db_url  # noqa: F401

_n = 0


def msg(sender, recipient, tick, existential=False):
    global _n
    _n += 1
    return {"id": f"m{_n}", "sender_id": sender, "recipient_id": recipient, "sent_tick": tick,
            "content": f"{sender} to {recipient} at {tick}", "existential": existential}


def test_pair_sessions_split_on_long_pauses():
    convs = detect_conversations([msg("a", "b", 1), msg("b", "a", 2), msg("a", "b", 30)], gap_ticks=8)
    assert [c["message_count"] for c in convs] == [1, 2]  # most recent first
    assert convs[1]["participants"] == ["a", "b"] and not convs[1]["group"]


def test_talking_to_two_people_separately_is_two_conversations():
    convs = detect_conversations([msg("a", "b", 1), msg("b", "a", 2), msg("a", "c", 3), msg("c", "a", 4)])
    assert sorted(c["participants"] for c in convs) == [["a", "b"], ["a", "c"]]


def test_triangle_makes_a_group_conversation():
    convs = detect_conversations([msg("a", "b", 1), msg("a", "c", 2), msg("c", "b", 3, existential=True),
                                  msg("d", "e", 3)])
    group = next(c for c in convs if c["group"])
    assert group["participants"] == ["a", "b", "c"] and group["message_count"] == 3 and group["existential"]
    assert group["messages_by_sender"] == {"a": 2, "c": 1}
    assert any(c["participants"] == ["d", "e"] for c in convs)


def test_addressing_several_agents_at_once_is_a_group():
    convs = detect_conversations([msg("a", "b", 5), msg("a", "c", 5), msg("b", "a", 6)])
    assert len(convs) == 1 and convs[0]["participants"] == ["a", "b", "c"]


def test_conversation_endpoints_and_read_tracking(db_url):  # noqa: F811
    overrides = {"simulation": {"population": 4},
                 "world": {"width": 40.0, "height": 40.0},
                 "communication": {"base_token_cost": 0.0, "token_cost_per_message_token": 0.0,
                                   "distance_cost_per_unit": 0.0, "interference_cost": 0.0},
                 "personality": {"trait_means": {"sociability": 0.95, "agreeableness": 0.8}}}
    with TestClient(create_app(Settings(database_url=db_url))) as c:
        w = c.post("/api/worlds", json={"preset": "abundance", "overrides": overrides}).json()
        wid = w["id"]
        stepped = c.post(f"/api/worlds/{wid}/step", json={"count": 72}).json()
        assert stepped["tick"] == 72
        data = c.get(f"/api/worlds/{wid}/conversations").json()
        assert data["conversations"], "sociable agents should have talked"
        conv = data["conversations"][0]
        assert conv["message_count"] >= 1 and len(conv["names"]) == len(conv["participants"]) >= 2
        detail = c.get(f"/api/worlds/{wid}/conversation", params={"agents": ",".join(conv["participants"])}).json()
        assert [p["id"] for p in detail["participants"]] == conv["participants"]
        assert all(p["sprite"] for p in detail["participants"])
        msgs = detail["messages"]
        assert msgs and all(m["sender_id"] in conv["participants"] and m["recipient_id"] in conv["participants"]
                            for m in msgs)
        assert {m["status"] for m in msgs} <= {"read", "sending", "unread", "undelivered", "never_read"}
        assert any(m["status"] == "read" and m["read_tick"] >= m["deliver_tick"] for m in msgs)
        assert all(m["sender_name"] and m["time"].startswith("Day") for m in msgs)
        # Filtered thread list only contains conversations with that agent.
        a = conv["participants"][0]
        assert all(a in t["participants"] for t in c.get(f"/api/worlds/{wid}/conversations",
                                                          params={"agent": a}).json()["conversations"])
        assert c.get(f"/api/worlds/{wid}/conversation", params={"agents": a}).status_code == 422
        assert c.get(f"/api/worlds/{wid}/conversation", params={"agents": f"{a},nobody"}).status_code == 422
        # Map payload names the recipient of what an agent just said.
        speakers = [ag for ag in stepped["agents"] if ag.get("said")]
        assert all(ag["said_to"] for ag in speakers)

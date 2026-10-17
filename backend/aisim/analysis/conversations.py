"""Group messages into conversations.

Messages are always one sender → one recipient. A *conversation* is a stretch of
messages between the same agents without a long pause:

1. Messages between one pair form a session; a gap longer than ``gap_ticks``
   between two of their messages starts a new session.
2. Sessions are merged into one group conversation when the agents really talk
   together, not just each with the same person:
   * a triangle: A–B, A–C and B–C sessions overlap in time, or
   * an address to several: one agent messages two or more of them in the same tick.

Pure functions over message dicts (``id``, ``sender_id``, ``recipient_id``,
``sent_tick``, ``content``, ``existential``), so they work on stored or live data.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

DEFAULT_GAP_TICKS = 8


class _Session:
    __slots__ = ("pair", "messages", "first", "last")

    def __init__(self, pair: tuple[str, str], message: dict[str, Any]):
        self.pair = pair
        self.messages = [message]
        self.first = self.last = message["sent_tick"]


def _sessions(messages: list[dict[str, Any]], gap: int) -> list[_Session]:
    open_by_pair: dict[tuple[str, str], _Session] = {}
    out: list[_Session] = []
    for m in sorted(messages, key=lambda m: (m["sent_tick"], str(m["id"]))):
        pair = tuple(sorted((m["sender_id"], m["recipient_id"])))
        current = open_by_pair.get(pair)
        if current is not None and m["sent_tick"] - current.last <= gap:
            current.messages.append(m)
            current.last = m["sent_tick"]
        else:
            current = _Session(pair, m)
            open_by_pair[pair] = current
            out.append(current)
    return out


def _overlap(a: _Session, b: _Session, gap: int) -> bool:
    return a.first <= b.last + gap and b.first <= a.last + gap


def detect_conversations(messages: list[dict[str, Any]], gap_ticks: int = DEFAULT_GAP_TICKS
                         ) -> list[dict[str, Any]]:
    """Conversations, most recent first: participants, span, counts and the last message."""
    sessions = _sessions(messages, gap_ticks)
    parent = list(range(len(sessions)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    by_agent: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(sessions):
        for agent in s.pair:
            by_agent[agent].append(i)
    by_pair: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, s in enumerate(sessions):
        by_pair[s.pair].append(i)

    # Triangles: A–B and A–C overlap, and B–C talked in the same stretch.
    for agent, idxs in by_agent.items():
        for i, j in combinations(idxs, 2):
            si, sj = sessions[i], sessions[j]
            if si.pair == sj.pair or not _overlap(si, sj, gap_ticks):
                continue
            b = si.pair[0] if si.pair[1] == agent else si.pair[1]
            c = sj.pair[0] if sj.pair[1] == agent else sj.pair[1]
            for k in by_pair.get(tuple(sorted((b, c))), []):
                sk = sessions[k]
                if _overlap(sk, si, gap_ticks) and _overlap(sk, sj, gap_ticks):
                    union(i, j)
                    union(i, k)

    # One agent addressing several others in the same tick.
    session_of_message: dict[str, int] = {str(m["id"]): i for i, s in enumerate(sessions) for m in s.messages}
    addressed: dict[tuple[str, int], list[str]] = defaultdict(list)
    for s in sessions:
        for m in s.messages:
            addressed[(m["sender_id"], m["sent_tick"])].append(str(m["id"]))
    for ids in addressed.values():
        recipients = {sessions[session_of_message[i]].pair for i in ids}
        if len(recipients) >= 2:
            for a, b in zip(ids, ids[1:]):
                union(session_of_message[a], session_of_message[b])

    groups: dict[int, list[_Session]] = defaultdict(list)
    for i, s in enumerate(sessions):
        groups[find(i)].append(s)
    conversations = []
    for members in groups.values():
        msgs = sorted((m for s in members for m in s.messages), key=lambda m: (m["sent_tick"], str(m["id"])))
        participants = sorted({a for s in members for a in s.pair})
        senders = defaultdict(int)
        for m in msgs:
            senders[m["sender_id"]] += 1
        last = msgs[-1]
        conversations.append({
            "id": f"{'-'.join(participants)}@{msgs[0]['sent_tick']}",
            "participants": participants,
            "first_tick": msgs[0]["sent_tick"],
            "last_tick": last["sent_tick"],
            "message_count": len(msgs),
            "messages_by_sender": dict(senders),
            "group": len(participants) > 2,
            "existential": any(m.get("existential") for m in msgs),
            "last_message": {k: last.get(k) for k in ("id", "sender_id", "recipient_id", "content", "sent_tick")},
        })
    conversations.sort(key=lambda c: (c["last_tick"], c["first_tick"]), reverse=True)
    return conversations

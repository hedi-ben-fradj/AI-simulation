"""Daily chronicle: what happened in the civilization on one day.

``build_digest`` condenses one day's records (events, messages, decisions,
memories, trust and trait changes, metrics and, when available, every agent's
state at nightfall) into a structured digest with ranked *highlights*: the
unusual or interesting things (deaths, thefts, new friendships, beliefs about
existence, unanswered messages, impossible plans...). ``template_story`` turns a
digest into a readable storyline without any model; an LLM narrator can write a
richer one from the same digest (``narrator_request``), and must not invent
events beyond it.

Pure functions over plain dicts, so they work on stored or live data.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from .conversations import detect_conversations

FRIEND_TRUST = 0.65
HOSTILE_TRUST = 0.35
# Action label for "time spent" sentences.
ACTIVITY_WORDS = {
    "work": "working", "rest": "resting", "eat": "eating", "buy_food": "buying food", "explore": "exploring",
    "reflect": "reflecting", "create": "creating", "study": "studying", "socialize": "socialising",
    "talk": "talking", "give": "giving", "offer_trade": "bargaining", "accept_trade": "trading",
    "reject_trade": "turning down offers", "steal": "stealing", "move": "travelling", "idle": "idling",
}


def _q(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _join(names: list[str]) -> str:
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _sentence(text: str) -> str:
    """End with a period unless it already ends a sentence (also inside a closing quote)."""
    t = text.rstrip()
    return t if t[-1:] in ".!?…" or t[-2:] in ('.”', '?”', '!”', '…”') else t + "."


def build_digest(*, day: int, from_tick: int, to_tick: int, ticks_per_day: int, names: dict[str, str],
                 events: list[dict[str, Any]], messages: list[dict[str, Any]], decisions: list[dict[str, Any]],
                 memories: list[dict[str, Any]], trust_changes: list[dict[str, Any]],
                 trait_changes: list[dict[str, Any]], metrics: list[dict[str, Any]],
                 agents: list[dict[str, Any]] | None = None, complete: bool = True) -> dict[str, Any]:
    """Digest of ticks ``from_tick`` .. ``to_tick - 1`` (day ``day``, 1-based).

    ``agents`` (optional) are nightfall states: id, name, alive, controller, health, hunger,
    energy, tokens, food, mood, action, sprite and optionally ``morning`` (same fields at dawn),
    ``hours`` (activity → hours today) and ``met_today`` (names first met today).
    """
    name = lambda aid: names.get(aid, aid) if aid else "someone"  # noqa: E731
    hours_per_tick = 24 / ticks_per_day
    highlights: list[dict[str, Any]] = []

    def hl(kind: str, score: int, text: str, agents_: list[str] | None = None, quote: str | None = None) -> None:
        highlights.append({"kind": kind, "score": score, "text": text, "agents": agents_ or [], "quote": quote})

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        by_type[e["type"]].append(e)
    counts = Counter({t: len(v) for t, v in by_type.items()})

    # ---- life and death
    for e in by_type["death"]:
        cause = str((e.get("data") or {}).get("cause", "unknown")).replace("_", " ")
        hl("death", 100, f"{name(e['agent_id'])} died ({cause}).", [e["agent_id"]])
    for e in by_type["birth"]:
        hl("birth", 80, e["summary"] + ".", [e["agent_id"]])
    for e in by_type["hazard"]:
        hl("injury", 55, e["summary"] + ".", [e["agent_id"]])
    for e in by_type["discovery"]:
        hl("discovery", 40, e["summary"] + ".", [e["agent_id"]])

    # ---- conflict and generosity
    for e in by_type["theft"]:
        d = e.get("data") or {}
        if d.get("detected"):
            text = f"{name(e['agent_id'])} was caught stealing from {name(e.get('target_id'))}."
        elif d.get("success"):
            text = f"{name(e['agent_id'])} secretly stole from {name(e.get('target_id'))} and got away with it."
        else:
            text = f"{name(e['agent_id'])} tried to steal from {name(e.get('target_id'))} but failed."
        hl("theft", 75, text, [e["agent_id"], e.get("target_id")])
    for e in by_type["give"]:
        hl("gift", 38, e["summary"] + ".", [e["agent_id"], e.get("target_id")])
    for e in by_type["trade"]:
        hl("trade", 36, e["summary"] + ".", [e["agent_id"], e.get("target_id")])
    for e in by_type["trade_rejected"]:
        if (e.get("data") or {}).get("help_request"):
            hl("refusal", 42, f"{name(e.get('target_id'))} asked {name(e['agent_id'])} for help and was refused.",
               [e["agent_id"], e.get("target_id")])
    creations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in by_type["create"]:
        creations[e["agent_id"]].append(e)
    for aid, works in creations.items():
        intent = (works[-1].get("data") or {}).get("intention")
        what = "a creative work" if len(works) == 1 else f"{len(works)} creative works"
        hl("creation", 30, f"{name(aid)} finished {what}.", [aid], quote=_q(intent) if intent else None)

    # ---- inner life
    for e in by_type["belief_update"]:
        d = e.get("data") or {}
        verb = "revised their belief" if d.get("previous") else "formed a belief"
        hl("belief", 58, f"{name(e['agent_id'])} {verb} about why they exist.", [e["agent_id"]],
           quote=_q(d.get("belief") or ""))
    existential_reflections = [e for e in by_type["reflect"] if (e.get("data") or {}).get("existential")]
    for aid, n in Counter(e["agent_id"] for e in existential_reflections).items():
        hl("contemplation", 32 + min(n, 6) * 2, f"{name(aid)} spent {n * hours_per_tick:g} hour"
           f"{'s' if n * hours_per_tick != 1 else ''} contemplating existence.", [aid])

    # ---- conversations
    convs = detect_conversations(messages, gap_ticks=max(4, ticks_per_day // 3))
    conversations = []
    for c in sorted(convs, key=lambda c: -c["message_count"])[:6]:
        part = set(c["participants"])
        msgs = [m for m in messages if m["sender_id"] in part and m["recipient_id"] in part
                and c["first_tick"] <= m["sent_tick"] <= c["last_tick"]]
        conversations.append({
            "participants": c["participants"], "names": [name(a) for a in c["participants"]],
            "message_count": c["message_count"], "group": c["group"], "existential": c["existential"],
            "excerpt": [{"from": name(m["sender_id"]), "to": name(m["recipient_id"]), "text": _q(m["content"], 220),
                         "tick": m["sent_tick"]} for m in msgs[:6]],
        })
    for c in conversations:
        if c["group"]:
            hl("group_talk", 50, f"{_join(c['names'])} talked together ({c['message_count']} messages).",
               c["participants"])
        if c["existential"]:
            hl("existential_talk", 48, f"{_join(c['names'])} discussed the meaning of existence.", c["participants"],
               quote=next((x["text"] for x in c["excerpt"]), None))
    # Messages carry a delivery status from the runtime (see runtime.views.message_status).
    unread = [m for m in messages if m.get("status") == "never_read"]
    if unread:
        senders = Counter(name(m["sender_id"]) for m in unread)
        who, n = senders.most_common(1)[0]
        hl("ignored", 30, f"{len(unread)} message{'s' if len(unread) > 1 else ''} expired unread "
           f"(most from {who}).", [])

    # ---- relationships
    pair_trust: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in trust_changes:
        pair_trust[(t["agent_id"], t["other_id"])].append(t)
    friendships, fallouts, swings = [], [], []
    for (a, b), changes in pair_trust.items():
        before, after = changes[0]["trust_before"], changes[-1]["trust_after"]
        swings.append({"from": name(a), "to": name(b), "before": round(before, 3), "after": round(after, 3)})
        if before < FRIEND_TRUST <= after:
            friendships.append((a, b, after))
        if before > HOSTILE_TRUST >= after:
            fallouts.append((a, b, after))
    for a, b, tr in friendships:
        hl("friendship", 60, f"{name(a)} came to trust {name(b)} (trust {tr:.2f}).", [a, b])
    for a, b, tr in fallouts:
        hl("distrust", 62, f"{name(a)} no longer trusts {name(b)} (trust {tr:.2f}).", [a, b])
    swings.sort(key=lambda s: -abs(s["after"] - s["before"]))

    # ---- thoughts: what agents intended (their visible reasoning) and reflected
    thoughts = []
    per_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in decisions:
        if d.get("visible_intention"):
            per_agent[d["agent_id"]].append(d)
    for aid, ds in per_agent.items():
        texts = Counter(d["visible_intention"] for d in ds)
        # Prefer the agent's most distinctive thoughts: LLM-written or existential ones first.
        ranked = sorted(ds, key=lambda d: (d.get("source") != "llm", not d.get("existential_active"),
                                           texts[d["visible_intention"]]))
        seen = set()
        for d in ranked:
            if d["visible_intention"] in seen:
                continue
            seen.add(d["visible_intention"])
            thoughts.append({"agent": name(aid), "agent_id": aid, "tick": d["tick"], "text": _q(d["visible_intention"]),
                             "source": d.get("source"), "existential": bool(d.get("existential_active"))})
            if len(seen) >= 2:
                break
    for m in memories:
        if m.get("source") == "agent" or m.get("kind") in ("reflection", "belief"):
            thoughts.append({"agent": name(m["agent_id"]), "agent_id": m["agent_id"], "tick": m["tick"],
                             "text": _q(m["content"]), "source": "memory", "existential": "existential" in (m.get("tags") or [])})
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for t in sorted(thoughts, key=lambda t: t["tick"]):
        unique.setdefault((t["agent_id"], t["text"]), t)
    thoughts = list(unique.values())

    # ---- plans the world refused
    rejected = [d for d in decisions if not d.get("valid") and d.get("reason")]
    llm_rejected = [d for d in rejected if d.get("source") == "llm"]
    for aid, n in Counter(d["agent_id"] for d in llm_rejected).items():
        reasons = Counter(d["reason"] for d in llm_rejected if d["agent_id"] == aid)
        top = reasons.most_common(1)[0][0].replace("_", " ")
        hl("impossible_plan", 28 + min(n, 5), f"{n} of {name(aid)}'s plans were impossible ({top}).", [aid])

    # ---- personality drift
    drift: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for t in trait_changes:
        drift[t["agent_id"]].append((t["trait"], t["new"] - t["old"]))
    for aid, items in drift.items():
        trait, delta = max(items, key=lambda x: abs(x[1]))
        if abs(delta) >= 0.03:
            hl("trait_change", 26, f"{name(aid)} became {'more' if delta > 0 else 'less'} "
               f"{trait.replace('_', ' ')} ({delta:+.2f}).", [aid])

    # ---- economy and population (metrics of the day's ticks)
    m0 = metrics[0] if metrics else {}
    m1 = metrics[-1] if metrics else {}
    economy = {
        "alive_start": m0.get("alive"), "alive_end": m1.get("alive"), "population": m1.get("population"),
        "tokens_mean_end": m1.get("tokens_mean"), "tokens_gini_end": m1.get("tokens_gini"),
        "food_stock_end": m1.get("food_stock_total"), "health_mean_end": m1.get("health_mean"),
        "hunger_mean_end": m1.get("hunger_mean"), "happiness_mean_end": m1.get("happiness_mean"),
        "stress_mean_end": m1.get("stress_mean"), "trust_mean_end": m1.get("trust_mean"),
        "friendships_end": m1.get("friendships"),
    }
    action_ticks: Counter[str] = Counter()
    for m in metrics:
        action_ticks.update(m.get("actions") or {})
    economy["hours_by_activity"] = {k: round(v * hours_per_tick, 1) for k, v in action_ticks.most_common()
                                    if k not in ("dead",)}
    if metrics and min(m.get("food_stock_total", 1) for m in metrics) == 0:
        hl("shortage", 50, "The food stores ran empty at some point.", [])
    if (m1.get("tokens_gini") or 0) >= 0.4:
        hl("inequality", 24, f"Wealth was very unequal (Gini {m1['tokens_gini']:.2f}).", [])

    # ---- agents at nightfall
    statuses = []
    if agents:
        for a in agents:
            morning = a.get("morning") or {}
            status = {k: a.get(k) for k in ("id", "name", "alive", "controller", "health", "hunger", "energy",
                                            "tokens", "food", "mood", "action", "sprite")}
            status["change"] = {k: round(a[k] - morning[k], 1) for k in ("health", "tokens", "hunger")
                                if isinstance(morning.get(k), (int, float)) and isinstance(a.get(k), (int, float))}
            status["hours"] = a.get("hours") or {}
            status["messages_sent"] = sum(1 for m in messages if m["sender_id"] == a["id"])
            status["messages_received"] = sum(1 for m in messages if m["recipient_id"] == a["id"])
            statuses.append(status)
            if a.get("alive") and a.get("health") is not None and a["health"] < 25:
                when = "tonight" if complete else "right now"
                hl("danger", 65, f"{a['name']} is in poor health {when} ({a['health']:.0f}/100).", [a["id"]])
            elif a.get("alive") and a.get("mood") in ("starving", "exhausted"):
                hl("danger", 45, f"{a['name']} {'ends the day' if complete else 'is'} {a['mood']}.", [a["id"]])
        # First meetings, as pairs (each meeting is seen from both sides).
        by_name = {a["name"]: a["id"] for a in agents}
        pairs = sorted({tuple(sorted((a["name"], other))) for a in agents for other in a.get("met_today") or []})
        if len(pairs) > 4:
            hl("first_meeting", 34, f"{len(pairs)} pairs of villagers met for the first time.", [])
        elif pairs:
            hl("first_meeting", 34, "First meeting" + ("s" if len(pairs) > 1 else "") + ": "
               + ", ".join(f"{x} and {y}" for x, y in pairs) + ".",
               [by_name.get(n) for p in pairs for n in p if by_name.get(n)])
        social_ids = {e["agent_id"] for e in events if e["type"] in ("socialize", "give", "trade", "message")} | \
            {e.get("target_id") for e in events if e["type"] in ("socialize", "give", "trade", "message")} | \
            {m["sender_id"] for m in messages} | {m["recipient_id"] for m in messages}
        alive = [a for a in agents if a.get("alive")]
        if len(alive) > 2:
            for a in alive:
                if a["id"] not in social_ids:
                    hl("isolation", 22, f"{a['name']} spoke to no one all day.", [a["id"]])

    highlights.sort(key=lambda h: -h["score"])
    stats = {
        "messages": len(messages), "conversations": len(convs), "gifts": counts["give"], "trades": counts["trade"],
        "refusals": counts["trade_rejected"], "thefts": counts["theft"], "deaths": counts["death"],
        "births": counts["birth"], "beliefs": counts["belief_update"],
        "existential_reflections": len(existential_reflections),
        "existential_messages": sum(1 for m in messages if m.get("existential")),
        "socialising": counts["socialize"], "artworks": counts["create"], "discoveries": counts["discovery"],
        "decisions": len(decisions), "rejected_plans": len(rejected),
        "llm_decisions": sum(1 for d in decisions if d.get("source") == "llm"),
    }
    return {
        "day": day, "from_tick": from_tick, "to_tick": to_tick, "complete": complete,
        "stats": stats, "economy": economy, "highlights": highlights, "conversations": conversations,
        "thoughts": thoughts[:24], "trust_swings": swings[:6], "agents": statuses,
    }


# ---------------------------------------------------------------- template writer

def _headline(d: dict[str, Any]) -> str:
    hs = d["highlights"]
    deaths = [h for h in hs if h["kind"] == "death"]
    if len(deaths) > 1:
        return f"A day of loss: {len(deaths)} villagers died"
    if deaths:
        return deaths[0]["text"].rstrip(".")
    top = hs[0] if hs else None
    if top and top["score"] >= 45:
        return top["text"].rstrip(".")
    econ = d["economy"]
    hours = econ.get("hours_by_activity") or {}
    if d["stats"]["messages"] >= 6:
        return "A talkative day in the village"
    if hours:
        main = next(iter(hours))
        return f"A quiet day of {ACTIVITY_WORDS.get(main, main)}"
    return "A quiet day"


def template_story(d: dict[str, Any]) -> tuple[str, str]:
    """(headline, markdown story) written from the digest alone, without a model."""
    s, econ = d["stats"], d["economy"]
    paras: list[str] = []
    alive_start, alive_end = econ.get("alive_start"), econ.get("alive_end")
    hours = econ.get("hours_by_activity") or {}
    busy = [f"{ACTIVITY_WORDS.get(k, k)} ({v:g} h)" for k, v in list(hours.items())[:3] if v]
    opening = f"Day {d['day']} {'began' if d['complete'] else 'has begun'} with {alive_start} villager" \
              f"{'s' if alive_start != 1 else ''} alive." if alive_start is not None else f"Day {d['day']}."
    if busy:
        opening += f" Most of the time went to {_join(busy)}."
    if econ.get("food_stock_end") is not None:
        opening += f" The food stores {'hold' if not d['complete'] else 'held'} {econ['food_stock_end']} meals at the end."
    paras.append(opening)

    social = []
    if s["messages"]:
        social.append(f"There were {s['messages']} message{'s' if s['messages'] != 1 else ''} in "
                      f"{s['conversations']} conversation{'s' if s['conversations'] != 1 else ''}.")
        for c in d["conversations"][:2]:
            ex = c["excerpt"]
            if not ex:
                continue
            line = f"{_join(c['names'])} exchanged {c['message_count']} message{'s' if c['message_count'] != 1 else ''}"
            line += f" — {ex[0]['from']}: “{ex[0]['text']}”"
            reply = next((x for x in ex[1:] if x["from"] != ex[0]["from"]), None)
            if reply:
                line += f" and {reply['from']} answered “{reply['text']}”"
            social.append(_sentence(line))
    else:
        social.append("No one sent a message.")
    for kind in ("gift", "trade", "refusal", "theft"):
        items = [h["text"] for h in d["highlights"] if h["kind"] == kind][:2]
        social.extend(items)
    if s["socialising"]:
        social.append(f"Villagers spent time together {s['socialising']} time{'s' if s['socialising'] != 1 else ''}.")
    paras.append(" ".join(social))

    inner = [h for h in d["highlights"] if h["kind"] in ("belief", "contemplation", "existential_talk", "creation")]
    if inner or d["thoughts"]:
        bits = []
        for h in inner[:3]:
            bits.append(h["text"] + (f" — “{h['quote']}”" if h.get("quote") else ""))
        if d["thoughts"] and len(bits) < 3:
            t = next((t for t in d["thoughts"] if t["source"] in ("llm", "memory")), d["thoughts"][0])
            bits.append(f"{t['agent']} was thinking: “{t['text']}”")
        paras.append("Inner life: " + " ".join(bits))

    unusual = [h for h in d["highlights"] if h["kind"] not in
               ("gift", "trade", "refusal", "theft", "belief", "contemplation", "existential_talk", "creation")]
    if unusual:
        paras.append("Worth noting: " + " ".join(h["text"] for h in unusual[:5]))

    if d["agents"]:
        lines = []
        for a in d["agents"]:
            if not a.get("alive"):
                lines.append(f"- **{a['name']}** — dead")
                continue
            change = a.get("change") or {}
            delta = f" ({change['tokens']:+g} today)" if change.get("tokens") else ""
            lines.append(f"- **{a['name']}** — health {a['health']:.0f}, hunger {a['hunger']:.0f}, "
                         f"{a['tokens']:.0f} tokens{delta}, {a['mood']}")
        paras.append(("**At nightfall**" if d["complete"] else "**Right now**") + "\n" + "\n".join(lines))
    elif alive_end is not None:
        paras.append(f"**At nightfall** {alive_end} villager{'s' if alive_end != 1 else ''} were alive"
                     + (f", with an average health of {econ['health_mean_end']:.0f}." if econ.get("health_mean_end") is not None else "."))
    return _headline(d), "\n\n".join(paras)


# ---------------------------------------------------------------- LLM narrator

NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "story": {"type": "string"},
        "notable": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "story", "notable"],
    "additionalProperties": False,
}

NARRATOR_SYSTEM = """You are the chronicler of a small simulated village of autonomous agents. Each evening you
write the storyline of the day for a researcher who reads it the next morning.

Rules:
- Use ONLY facts in the day's digest (JSON). Do not invent events, motives or dialogue. You may quote
  messages and thoughts from the digest verbatim (short quotes).
- Past tense, plain and vivid, 3 to 6 short paragraphs of markdown (no headings). Mention the overall
  state (food, health, mood), the conversations and relationships, what agents were thinking, and
  anything unusual or interesting. Connect to earlier days when the digest's "previously" helps.
- Refer to agents by name; use "they" when a pronoun is needed.
- "headline": one line, at most 12 words, the most important thing that happened.
- "notable": 0 to 5 short bullet strings with the most unusual or interesting things (empty if none).
- The agents are simulated; do not claim they are conscious.
"""


def narrator_request(digest: dict[str, Any], previous: list[dict[str, Any]]) -> tuple[str, str]:
    """System prompt and user message for an LLM narrator."""
    payload = {
        "previously": [{"day": p["day"], "headline": p["headline"]} for p in previous[-3:]],
        "day": digest,
    }
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return NARRATOR_SYSTEM, f"Digest of day {digest['day']}:\n{text}"


def parse_narrative(text: str) -> tuple[str, str, list[str]]:
    raw = text.strip()
    if not raw.startswith("{") and "{" in raw:
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
    data = json.loads(raw)
    headline = " ".join(str(data["headline"]).split())[:200]
    story = str(data["story"]).strip()
    if not headline or not story:
        raise ValueError("empty narrative")
    notable = [str(x) for x in (data.get("notable") or [])][:8]
    return headline, story, notable

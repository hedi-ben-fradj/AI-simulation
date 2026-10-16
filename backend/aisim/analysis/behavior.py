"""Do personality traits actually change behaviour?

Each agent's lifetime behaviour is reduced to comparable rates (share of time
per activity, events per day). Each *initial* trait (traits drift with
behaviour, so current values would be circular) is correlated (Pearson) with the
behaviours it is *expected* to drive (pre-registered hypotheses below), and the
full trait x behaviour matrix is available for exploration.

Small populations give noisy correlations; ``n`` is reported with every value
and results should be pooled across runs (see the experiment service) before
drawing conclusions.
"""

from __future__ import annotations

import math
from typing import Any

from ..engine.state import TRAITS

ACTIVITY_GROUPS: dict[str, tuple[str, ...]] = {
    "work_share": ("work",),
    "social_share": ("socialize", "talk", "give", "offer_trade", "accept_trade", "reject_trade"),
    "create_share": ("create",),
    "study_share": ("study",),
    "explore_share": ("explore",),
    "reflect_share": ("reflect",),
    "rest_share": ("rest",),
}

# (trait, behaviour, expected sign)
HYPOTHESES: list[tuple[str, str, int]] = [
    ("sociability", "social_share", 1),
    ("artistic", "create_share", 1),
    ("scientific_curiosity", "study_share", 1),
    ("curiosity", "explore_share", 1),
    ("ambition", "work_share", 1),
    ("spirituality", "existential_activation_rate", 1),
    ("spirituality", "reflect_share", 1),
    ("generosity", "gifts_per_day", 1),
    ("criminal_tendency", "thefts_per_day", 1),
    ("honesty", "thefts_per_day", -1),
]


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-12 or syy <= 1e-12:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def agent_behaviour(agent: Any, ticks_per_day: int) -> dict[str, float]:
    alloc = agent.time_allocation
    total = sum(alloc.values()) or 1
    days = max(1e-9, total / ticks_per_day)
    out = {name: sum(alloc.get(a, 0) for a in acts) / total for name, acts in ACTIVITY_GROUPS.items()}
    st = agent.stats
    ex = agent.existential
    out.update({
        "gifts_per_day": st.get("gifts_given", 0) / days,
        "thefts_per_day": st.get("thefts_attempted", 0) / days,
        "messages_per_day": st.get("messages_sent", 0) / days,
        "existential_activation_rate": ex.activations / ex.opportunities if ex.opportunities else 0.0,
        "existential_conversations_per_day": ex.conversations / days,
        "tokens_earned_per_day": st.get("tokens_earned", 0) / days,
    })
    return out


def behaviour_table(agents: list[Any], ticks_per_day: int, min_ticks: int = 24) -> list[dict[str, Any]]:
    """One row per agent that lived long enough to say something."""
    rows = []
    for a in agents:
        if sum(a.time_allocation.values()) < min_ticks:
            continue
        traits = dict(a.initial_personality or a.personality)
        rows.append({"agent_id": a.id, "name": a.name, "alive": a.alive, "traits": traits,
                     "current_traits": dict(a.personality),
                     "behaviour": agent_behaviour(a, ticks_per_day)})
    return rows


def correlations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    behaviours = sorted(rows[0]["behaviour"]) if rows else []
    matrix: dict[str, dict[str, float | None]] = {}
    for t in TRAITS:
        xs = [r["traits"][t] for r in rows]
        matrix[t] = {}
        for b in behaviours:
            r = pearson(xs, [row["behaviour"][b] for row in rows])
            matrix[t][b] = None if r is None else round(r, 3)
    hyps = []
    for trait, beh, sign in HYPOTHESES:
        r = matrix.get(trait, {}).get(beh)
        hyps.append({
            "trait": trait, "behaviour": beh, "expected_sign": sign, "r": r, "n": len(rows),
            "supported": None if r is None else (r * sign > 0.2),
        })
    return {"n": len(rows), "behaviours": behaviours, "matrix": matrix, "hypotheses": hyps}


def existential_summary(agents: list[Any]) -> dict[str, Any]:
    per_agent = []
    for a in agents:
        ex = a.existential
        per_agent.append({
            "agent_id": a.id, "name": a.name, "alive": a.alive, "controller": a.controller,
            "spirituality": (a.initial_personality or a.personality).get("spirituality"),
            "activations": ex.activations, "opportunities": ex.opportunities,
            "activation_rate": round(ex.activations / ex.opportunities, 4) if ex.opportunities else 0.0,
            "ticks_contemplating": ex.ticks_contemplating, "conversations": ex.conversations,
            "reflections": ex.reflections, "beliefs": ex.beliefs, "belief_revisions": max(0, len(ex.beliefs) - 1),
            "mean_happiness": a.emotion("happiness"),
        })
    acts = sum(p["activations"] for p in per_agent)
    opps = sum(p["opportunities"] for p in per_agent)
    return {
        "activation_rate": round(acts / opps, 4) if opps else 0.0,
        "agents_with_beliefs": sum(1 for p in per_agent if p["beliefs"]),
        "per_agent": per_agent,
    }


def analyse_world(sim: Any) -> dict[str, Any]:
    agents = list(sim.world.agents.values())
    rows = behaviour_table(agents, sim.config.simulation.ticks_per_day)
    return {
        "tick": sim.world.tick,
        "behaviour": rows,
        "correlations": correlations(rows),
        "existential": existential_summary(agents),
        "caveat": "Correlations from a single small population are noisy; pool runs with the experiment service.",
    }

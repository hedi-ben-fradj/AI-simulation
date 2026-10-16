"""Competing goals and their momentary salience.

Every agent holds the same set of goal types; personality and current state
determine how salient each one is. Only the top ``max_active_goals`` are
active at a time (attention is finite). Survival always outranks the rest when
needs are pressing; the existential goal stays in the background unless it has
been activated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .simulation import Simulation
    from .state import Agent

GOAL_LABELS = {
    "survival": "Stay alive: keep hunger, energy and health in a safe range",
    "economic": "Secure enough tokens for food and future needs",
    "social": "Find companionship, friendship and cooperation",
    "creative": "Express yourself by creating something",
    "scientific": "Understand how the world works",
    "existential": "Understand why you exist and what your purpose is",
}


def _c(v: float) -> float:
    return max(0.0, min(1.0, v))


def compute_goals(sim: "Simulation", agent: "Agent") -> list[dict[str, Any]]:
    rc = sim.config.resources
    p = agent.personality
    survival = max(
        agent.hunger / max(1.0, rc.maximum_hunger) * 1.2,
        (1 - agent.energy / rc.maximum_energy) * 0.9,
        (1 - agent.health / rc.maximum_health) * 1.3,
    )
    reserve = rc.food_price * 6
    economic = _c(1 - agent.tokens / reserve) * (0.6 + 0.4 * p["ambition"]) + 0.15 * p["ambition"]
    free = _c(1 - survival)
    social = agent.emotion("loneliness") * (0.4 + 0.6 * p["sociability"]) + 0.1 * p["sociability"]
    creative = 0.5 * p["artistic"] * free
    scientific = 0.5 * (0.6 * p["scientific_curiosity"] + 0.4 * p["curiosity"]) * free
    existential = 0.15 * p["spirituality"] * free + (0.5 if agent.existential.active else 0.0)
    raw = {
        "survival": _c(survival),
        "economic": _c(economic),
        "social": _c(social),
        "creative": _c(creative),
        "scientific": _c(scientific),
        "existential": _c(existential),
    }
    ranked = sorted(raw.items(), key=lambda kv: (-kv[1], kv[0]))
    limit = sim.config.capacity.max_active_goals
    active = {k for k, v in ranked[:limit] if v >= 0.12}
    if raw["survival"] >= 0.5:
        active.add("survival")
        if len(active) > limit:
            weakest = min((k for k in active if k != "survival"), key=lambda k: raw[k], default=None)
            if weakest:
                active.discard(weakest)
    return [
        {"id": k, "label": GOAL_LABELS[k], "salience": round(v, 3), "active": k in active}
        for k, v in ranked
    ]

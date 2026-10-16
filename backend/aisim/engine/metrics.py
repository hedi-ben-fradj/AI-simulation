"""Civilization-level metrics collected every tick."""

from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .simulation import Simulation, TickResult


def gini(values: list[float]) -> float:
    vals = sorted(max(0.0, v) for v in values)
    n = len(vals)
    total = sum(vals)
    if n == 0 or total <= 0:
        return 0.0
    cum = sum((i + 1) * v for i, v in enumerate(vals))
    return round((2 * cum) / (n * total) - (n + 1) / n, 4)


def _m(values: list[float]) -> float:
    return round(mean(values), 4) if values else 0.0


def compute_metrics(sim: "Simulation", result: "TickResult") -> dict[str, Any]:
    world = sim.world
    agents = list(world.agents.values())
    alive = [a for a in agents if a.alive]
    dead = [a for a in agents if not a.alive]
    events = Counter(e.type for e in result.events)
    trades = sum(1 for e in result.events if e.type == "trade" and not e.data.get("help"))
    helps = sum(1 for e in result.events if e.type == "trade" and e.data.get("help"))
    successful_thefts = sum(1 for e in result.events if e.type == "theft" and e.data.get("success"))
    trust_values = [r.trust for a in alive for r in a.relationships.values()]
    actions = Counter(sim.executed.get(a.id, "idle") for a in alive)
    return {
        "tick": world.tick,
        "day": world.tick // sim.config.simulation.ticks_per_day + 1,
        "population": len(agents),
        "alive": len(alive),
        "deaths_total": len(dead),
        "deaths_by_cause": dict(Counter((a.death or {}).get("cause", "unknown") for a in dead)),
        "deaths_this_tick": len(result.deaths),
        "tokens_mean": _m([a.tokens for a in alive]),
        "tokens_total": round(sum(a.tokens for a in alive), 3),
        "tokens_gini": gini([a.tokens for a in alive]),
        "food_inventory_total": sum(a.food for a in alive),
        "food_stock_total": sum((l.stock or 0) for l in world.locations.values() if l.type == "food"),
        "hunger_mean": _m([a.hunger for a in alive]),
        "energy_mean": _m([a.energy for a in alive]),
        "health_mean": _m([a.health for a in alive]),
        "happiness_mean": _m([a.emotion("happiness") for a in alive]),
        "stress_mean": _m([a.emotion("stress") for a in alive]),
        "loneliness_mean": _m([a.emotion("loneliness") for a in alive]),
        "knowledge_mean": _m([a.knowledge for a in alive]),
        "artworks_total": sum(a.artworks for a in agents),
        "actions": dict(actions),
        "messages_sent": len(result.messages),
        "message_token_cost": round(sum(m.token_cost for m in result.messages), 5),
        "trades": trades,
        "help_given": helps,
        "gifts": events.get("give", 0),
        "refusals": events.get("trade_rejected", 0),
        "thefts": events.get("theft", 0),
        "thefts_successful": successful_thefts,
        "trust_mean": _m(trust_values),
        "relationships": len(trust_values),
        "existential_activations": sum(1 for d in result.decisions if d.existential_active),
        "existential_reflections": sum(1 for e in result.events if e.type == "reflect" and e.data.get("existential")),
        "existential_messages": sum(1 for m in result.messages if m.existential),
        "existential_probability_mean": _m([a.existential.last_probability for a in alive]),
        "decisions": len(result.decisions),
        "decisions_rejected": sum(1 for d in result.decisions if not d.valid),
        "decisions_fallback": sum(1 for d in result.decisions if d.source == "fallback"),
        "trait_changes": len(result.trait_changes),
    }

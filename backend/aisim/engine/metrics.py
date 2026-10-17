"""Civilization-level metrics collected every tick."""

from __future__ import annotations

from collections import Counter
import math

from .state import TRAITS
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
    # math.fsum is ~50x faster than statistics.mean (which uses exact fractions).
    return round(math.fsum(values) / len(values), 4) if values else 0.0


FRIEND_TRUST = 0.6
HOSTILE_TRUST = 0.35


def social_network_metrics(alive: list) -> dict[str, Any]:
    """Network structure among living agents (directed trust, mutual ties)."""
    ids = {a.id for a in alive}
    by_id = {a.id: a for a in alive}
    friendships = hostile = mutual_known = 0
    for a in alive:
        for oid, rel in a.relationships.items():
            if oid not in ids or oid <= a.id:
                continue
            back = by_id[oid].relationships.get(a.id)
            if back is None:
                continue
            mutual_known += 1
            if rel.trust >= FRIEND_TRUST and back.trust >= FRIEND_TRUST and min(rel.familiarity, back.familiarity) >= 2:
                friendships += 1
            if rel.trust <= HOSTILE_TRUST or back.trust <= HOSTILE_TRUST:
                hostile += 1
    n = len(alive)
    interacted = [(a, r) for a in alive for oid, r in a.relationships.items() if oid in ids and r.familiarity > 0]
    possible = n * (n - 1)
    isolated = sum(1 for a in alive if not any(r.familiarity > 0 for oid, r in a.relationships.items() if oid in ids))
    return {
        "friendships": friendships,
        "hostile_pairs": hostile,
        "known_pairs": mutual_known,
        "network_density": round(len(interacted) / possible, 4) if possible else 0.0,
        "isolated_agents": isolated,
    }


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
    social = social_network_metrics(alive)
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
        **social,
        "existential_activations": sum(1 for d in result.decisions if d.existential_active),
        "existential_reflections": sum(1 for e in result.events if e.type == "reflect" and e.data.get("existential")),
        "existential_messages": sum(1 for m in result.messages if m.existential),
        "existential_probability_mean": _m([a.existential.last_probability for a in alive]),
        "decisions": len(result.decisions),
        "decisions_rejected": sum(1 for d in result.decisions if not d.valid),
        "decisions_fallback": sum(1 for d in result.decisions if d.source == "fallback"),
        "trait_changes": len(result.trait_changes),
        "traits_mean": {t: _m([a.personality[t] for a in alive]) for t in TRAITS},
    }

"""Memory retrieval for decision contexts.

Agents only ever retrieve their own memories. Each memory is scored by
importance, recency and relevance to the current decision (agents involved,
topics suggested by current needs); the context builder then keeps as many of
the top-scoring memories as its budget allows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ..engine.simulation import Simulation
    from ..engine.state import Agent, Memory

W_IMPORTANCE = 0.5
W_RECENCY = 0.3
W_RELEVANCE = 0.4


def relevant_tags(sim: "Simulation", agent: "Agent", existential_active: bool) -> set[str]:
    tags: set[str] = set()
    if agent.hunger >= 50 or agent.tokens < sim.config.resources.food_price * 2:
        tags |= {"gift", "trade", "refusal", "discovery", "theft"}
    if existential_active:
        tags |= {"existential", "belief", "death", "reflection"}
    if agent.emotion("loneliness") > 0.5:
        tags |= {"meeting", "gift", "trade"}
    if agent.emotion("safety") < 0.5:
        tags |= {"danger", "theft", "death"}
    return tags


def score(sim: "Simulation", memory: "Memory", involved: set[str], tags: set[str]) -> float:
    tpd = sim.config.simulation.ticks_per_day
    age_days = max(0.0, (sim.world.tick - memory.tick) / tpd)
    recency = 1.0 / (1.0 + age_days)
    relevance = 0.0
    if involved and set(memory.related_agents) & involved:
        relevance += 0.7
    if tags and set(memory.tags) & tags:
        relevance += 0.5
    if memory.kind == "belief":
        relevance += 0.2
    return W_IMPORTANCE * memory.importance + W_RECENCY * recency + W_RELEVANCE * min(1.0, relevance)


def retrieve(sim: "Simulation", agent: "Agent", involved: set[str], existential_active: bool,
             limit: int = 12) -> list["Memory"]:
    tags = relevant_tags(sim, agent, existential_active)
    ranked = sorted(agent.memories, key=lambda m: (-score(sim, m, involved, tags), -m.tick, m.id))
    return ranked[:limit]

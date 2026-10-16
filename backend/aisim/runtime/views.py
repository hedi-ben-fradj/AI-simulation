"""Serialisable views of simulation state for the API and WebSocket clients.

These are researcher views (the UI is an observation tool), so they include
internal state. They are never fed to agents; agent prompts are built by the
context builder, which enforces information boundaries.
"""

from __future__ import annotations

from typing import Any

from ..engine.simulation import Simulation, TickResult
from ..engine.state import TRAIT_DESCRIPTIONS, Agent


def agent_brief(sim: Simulation, a: Agent, said: dict[str, str] | None = None) -> dict[str, Any]:
    task = a.current_task
    return {
        "id": a.id, "name": a.name, "x": round(a.x, 2), "y": round(a.y, 2), "alive": a.alive,
        "controller": a.controller, "action": a.current_action if a.alive else "dead",
        "traveling": bool(task and task.travel_to), "intention": a.visible_intention, "mood": a.current_mood,
        "health": round(a.health, 1), "energy": round(a.energy, 1), "hunger": round(a.hunger, 1),
        "tokens": round(a.tokens, 2), "food": a.food, "existential_active": a.existential.active,
        "said": (said or {}).get(a.id),
    }


def world_view(sim: Simulation, status: str, speed: float, extra: dict[str, Any] | None = None,
               result: TickResult | None = None) -> dict[str, Any]:
    said: dict[str, str] = {}
    if result is not None:
        for m in result.messages:
            said[m.sender_id] = m.content
    w = sim.world
    return {
        "id": w.id, "name": w.name, "tick": w.tick, "time": sim.time_label(), "day": sim.day + 1,
        "ticks_per_day": sim.config.simulation.ticks_per_day, "status": status, "speed": speed,
        "width": w.width, "height": w.height,
        "locations": [loc.model_dump() for loc in w.locations.values()],
        "agents": [agent_brief(sim, a, said) for a in w.agents.values()],
        **(extra or {}),
    }


def tick_payload(sim: Simulation, result: TickResult, status: str, speed: float,
                 extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "tick",
        "world": world_view(sim, status, speed, extra, result),
        "metrics": result.metrics,
        "events": [e.model_dump() for e in result.events if e.importance >= 0.1 or e.type in ("work", "eat")],
        "messages": [m.model_dump() for m in result.messages],
        "decisions": [d.to_dict() for d in result.decisions],
    }


def agent_detail(sim: Simulation, agent_id: str) -> dict[str, Any] | None:
    a = sim.world.agents.get(agent_id)
    if a is None:
        return None
    data = a.model_dump(mode="json")
    data["relationships"] = sorted((
        {**r.model_dump(), "trust": round(r.trust, 4),
         "other_alive": sim.world.agents[r.other_id].alive if r.other_id in sim.world.agents else False}
        for r in a.relationships.values()), key=lambda r: -r["trust"])
    data["trait_descriptions"] = TRAIT_DESCRIPTIONS
    data["memories"] = sorted(data["memories"], key=lambda m: -m["tick"])
    data["pending_offers"] = [o.model_dump() for o in sim.world.trade_offers.values()
                              if o.status == "pending" and agent_id in (o.from_id, o.to_id)]
    return data

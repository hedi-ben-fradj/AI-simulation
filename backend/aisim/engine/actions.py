"""Action catalog.

Every action declares its preconditions, duration limits, and per-tick costs.
Agents (rule-based or LLM) only produce :class:`ActionProposal` objects; the
validation layer (``validation.py``) turns a proposal into a committed
:class:`~aisim.engine.state.Task` or rejects it, and the per-tick handlers
registered here apply the deterministic consequences.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from .state import Agent, Location, Task

if TYPE_CHECKING:  # pragma: no cover
    from .simulation import Simulation


class ActionProposal(BaseModel):
    """What an agent wants to do. Never trusted; always validated."""

    model_config = ConfigDict(extra="ignore")

    action: str
    target: str | None = None
    duration: int | None = None
    quantity: int | None = None
    resource_offer: dict[str, float] | None = None
    resource_request: dict[str, float] | None = None
    message: str | None = None
    message_to: str | None = None
    # Additional messages beyond the first; still limited by outgoing capacity.
    extra_messages: list[dict[str, str]] = Field(default_factory=list)
    visible_intention: str | None = None
    memory_candidates: list[Any] = Field(default_factory=list)
    belief: str | None = None
    confidence: float | None = None
    source: str = "rule"


# A tick handler returns "continue", "done" or "failed:<reason>".
TickHandler = Callable[["Simulation", Agent, Task, float], str]
CheckHandler = Callable[["Simulation", Agent, ActionProposal, Task], "str | None"]


@dataclass
class ActionSpec:
    name: str
    description: str
    tick: TickHandler
    location_type: str | None = None
    target_kind: str | None = None  # agent | location | offer | place
    target_required: bool = False
    proximity: bool = False  # must be within interaction radius of the target agent
    # Location type to travel to when an optional agent target is omitted.
    location_fallback: str | None = None
    requires_message: bool = False
    min_duration: int = 1
    max_duration: Callable[[Any], int] | int = 1
    default_duration: int = 1
    energy_per_tick: Callable[[Any], float] | float = 0.0
    attention_cost: float = 0.0
    check: CheckHandler | None = None
    category: str = "core"
    enabled: Callable[[Any], bool] = field(default=lambda config: True)

    def max_ticks(self, config) -> int:
        return self.max_duration(config) if callable(self.max_duration) else self.max_duration

    def energy_cost(self, config) -> float:
        return self.energy_per_tick(config) if callable(self.energy_per_tick) else self.energy_per_tick


REGISTRY: dict[str, ActionSpec] = {}


def register(spec: ActionSpec) -> ActionSpec:
    REGISTRY[spec.name] = spec
    return spec


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def at_location(agent: Agent, loc: Location) -> bool:
    return distance(agent.x, agent.y, loc.x, loc.y) <= loc.radius + 1e-6


def current_location(sim: "Simulation", agent: Agent) -> Location | None:
    best, best_d = None, float("inf")
    for loc in sim.world.locations.values():
        d = distance(agent.x, agent.y, loc.x, loc.y)
        if d <= loc.radius + 1e-6 and d < best_d:
            best, best_d = loc, d
    return best


def nearest_location(sim: "Simulation", agent: Agent, ltype: str) -> Location | None:
    candidates = [l for l in sim.world.locations.values() if l.type == ltype]
    if not candidates:
        return None
    return min(candidates, key=lambda l: (distance(agent.x, agent.y, l.x, l.y), l.id))


# Positions are rounded, so arrival needs a tolerance larger than the rounding step.
ARRIVAL_TOLERANCE = 0.05


def step_towards(sim: "Simulation", agent: Agent, tx: float, ty: float, stop_within: float = 0.0) -> bool:
    """Move the agent one tick towards (tx, ty). Returns True when arrived."""
    wc = sim.config.world
    d = distance(agent.x, agent.y, tx, ty)
    if d <= stop_within + ARRIVAL_TOLERANCE:
        return True
    travel = min(wc.movement_speed_per_tick, d - stop_within)
    if agent.energy < 5:
        travel *= 0.5  # exhausted agents move slower
    agent.x += (tx - agent.x) / d * travel
    agent.y += (ty - agent.y) / d * travel
    agent.x = round(min(max(agent.x, 0.0), wc.width), 3)
    agent.y = round(min(max(agent.y, 0.0), wc.height), 3)
    sim.spend_energy(agent, travel * wc.movement_energy_per_unit)
    agent.bump_stat("distance_travelled", travel)
    return distance(agent.x, agent.y, tx, ty) <= stop_within + ARRIVAL_TOLERANCE


def travel_ticks(sim: "Simulation", agent: Agent, tx: float, ty: float, stop_within: float = 0.0) -> int:
    d = max(0.0, distance(agent.x, agent.y, tx, ty) - stop_within)
    return math.ceil(d / sim.config.world.movement_speed_per_tick) if d > 1e-6 else 0


# --------------------------------------------------------------------------
# Core action handlers
# --------------------------------------------------------------------------

def _tick_idle(sim, agent, task, time_fraction):
    return "continue"


def _tick_move(sim, agent, task, time_fraction):
    # Arrival is handled by the generic travel phase; reaching here means done.
    return "done"


def _check_move(sim, agent, proposal, task):
    if task.target is None:
        return "invalid_target"
    return None


def _work_capacity_left(sim, agent) -> int:
    return agent.work_capacity - agent.work_ticks_today


def workers_committed(sim: "Simulation", loc: Location, exclude: str | None = None) -> int:
    """Agents already committed to working at ``loc`` (visible to anyone looking)."""
    return sum(
        1 for a in sim.world.agents.values()
        if a.alive and a.id != exclude and a.current_task is not None
        and a.current_task.action == "work" and a.current_task.target == loc.id
    )


def _check_work(sim, agent, proposal, task):
    if _work_capacity_left(sim, agent) <= 0:
        return "work_capacity_exhausted"
    loc = sim.world.locations.get(task.target or "")
    if loc is not None and loc.capacity is not None and workers_committed(sim, loc, agent.id) >= loc.capacity:
        # Prefer another workplace with a free slot before giving up.
        free = [l for l in sim.world.locations.values() if l.type == "workplace" and l.id != loc.id
                and (l.capacity is None or workers_committed(sim, l, agent.id) < l.capacity)]
        if proposal.target or not free:
            return "workplace_full"
        alt = min(free, key=lambda l: (distance(agent.x, agent.y, l.x, l.y), l.id))
        task.target = alt.id
        task.travel_to = None if at_location(agent, alt) else alt.id
    task.total_ticks = task.remaining_ticks = min(task.total_ticks, _work_capacity_left(sim, agent))
    return None


def _tick_work(sim, agent, task, time_fraction):
    wc = sim.config.work
    loc = sim.world.locations[task.target]
    if _work_capacity_left(sim, agent) <= 0:
        return "failed:work_capacity_exhausted"
    if loc.capacity is not None and loc.occupancy >= loc.capacity:
        return "failed:workplace_full"
    fatigued = agent.energy < wc.fatigue_energy_threshold
    workload_multiplier = wc.fatigue_workload_multiplier if fatigued else 1.0
    overtime = max(0, agent.work_ticks_today + 1 - wc.overtime_after_ticks_per_day)
    workload = time_fraction * workload_multiplier + overtime * wc.overtime_workload_increment
    energy_cost = wc.energy_cost_per_tick * time_fraction * workload_multiplier
    if energy_cost > agent.energy:
        return "failed:insufficient_energy"
    productivity = sim.productivity(agent)
    tokens = wc.base_wage_per_tick * productivity * time_fraction * loc.wage_multiplier
    health_cost = max(0.0, workload - wc.safe_workload) * wc.health_penalty_rate
    loc.occupancy += 1
    agent.tokens = round(agent.tokens + tokens, 4)
    sim.spend_energy(agent, energy_cost)
    if health_cost > 0:
        sim.damage(agent, health_cost, "overwork")
    agent.work_ticks_today += 1
    agent.bump_stat("tokens_earned", tokens)
    agent.bump_stat("work_ticks")
    sim.emit("work", f"{agent.name} worked at {loc.name} (+{tokens:.1f} tokens)", agent=agent,
             data={"tokens": round(tokens, 3), "energy_cost": round(energy_cost, 3),
                   "health_cost": round(health_cost, 3), "location": loc.id, "workload": round(workload, 3)},
             importance=0.1)
    return "continue"


def _check_eat(sim, agent, proposal, task):
    if agent.food > 0:
        task.params["from_inventory"] = True
        task.target = None
        task.travel_to = None
        return None
    loc = sim.world.locations.get(task.target) if task.target else None
    if loc is None or loc.type != "food":
        return "no_food_available"
    if (loc.stock or 0) <= 0:
        return "food_out_of_stock"
    if agent.tokens < (loc.price or 0):
        return "insufficient_tokens"
    return None


def _tick_eat(sim, agent, task, time_fraction):
    rc = sim.config.resources
    if task.params.get("from_inventory") and agent.food > 0:
        agent.food -= 1
        source = "inventory"
    else:
        loc = sim.world.locations[task.target]
        if (loc.stock or 0) <= 0:
            return "failed:food_out_of_stock"
        if agent.tokens < (loc.price or 0):
            return "failed:insufficient_tokens"
        loc.stock -= 1
        agent.tokens = round(agent.tokens - (loc.price or 0), 4)
        agent.bump_stat("tokens_spent_food", loc.price or 0)
        source = loc.name
    before = agent.hunger
    agent.hunger = max(0.0, agent.hunger - rc.food_nutrition)
    agent.bump_stat("meals")
    sim.emit("eat", f"{agent.name} ate ({source})", agent=agent,
             data={"hunger_before": round(before, 2), "hunger_after": round(agent.hunger, 2), "source": source},
             importance=0.1)
    return "done"


def _check_buy_food(sim, agent, proposal, task):
    loc = sim.world.locations.get(task.target) if task.target else None
    if loc is None or loc.type != "food":
        return "invalid_target"
    qty = max(1, int(proposal.quantity or 1))
    space = sim.config.resources.maximum_food_inventory - agent.food
    if space <= 0:
        return "inventory_full"
    qty = min(qty, space)
    if (loc.stock or 0) < qty:
        qty = loc.stock or 0
        if qty <= 0:
            return "food_out_of_stock"
    if agent.tokens < qty * (loc.price or 0):
        qty = int(agent.tokens // (loc.price or 1))
        if qty <= 0:
            return "insufficient_tokens"
    task.params["quantity"] = qty
    return None


def _tick_buy_food(sim, agent, task, time_fraction):
    loc = sim.world.locations[task.target]
    qty = min(task.params.get("quantity", 1), loc.stock or 0,
              sim.config.resources.maximum_food_inventory - agent.food)
    price = loc.price or 0
    if price > 0:
        qty = min(qty, int(agent.tokens // price))
    if qty <= 0:
        return "failed:cannot_buy_food"
    loc.stock -= qty
    agent.food += qty
    agent.tokens = round(agent.tokens - qty * price, 4)
    agent.bump_stat("tokens_spent_food", qty * price)
    sim.emit("buy_food", f"{agent.name} bought {qty} food at {loc.name}", agent=agent,
             data={"quantity": qty, "cost": qty * price, "location": loc.id}, importance=0.1)
    return "done"


def _tick_rest(sim, agent, task, time_fraction):
    rc = sim.config.resources
    loc = current_location(sim, agent)
    mult = rc.rest_area_recovery_multiplier if loc is not None and loc.type == "rest" else 1.0
    gained = min(rc.maximum_energy - agent.energy, rc.rest_energy_recovery_per_tick * mult * time_fraction)
    agent.energy += gained
    if agent.hunger < rc.health_recovery_max_hunger:
        agent.health = min(rc.maximum_health, agent.health + rc.rest_health_recovery_per_tick * time_fraction)
    sim.adjust_emotion(agent, "stress", -0.05)
    agent.bump_stat("rest_ticks")
    return "continue"


def _explore_energy(config) -> float:
    return 5.0


def _tick_explore(sim, agent, task, time_fraction):
    wc = sim.config.world
    rng = sim.streams["environment"]
    if "dest" not in task.params:
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0.5, 1.0) * wc.explore_distance
        tx = min(max(agent.x + dist * math.cos(angle), 0), wc.width)
        ty = min(max(agent.y + dist * math.sin(angle), 0), wc.height)
        task.params["dest"] = [round(tx, 2), round(ty, 2)]
    tx, ty = task.params["dest"]
    step_towards(sim, agent, tx, ty)
    sim.spend_energy(agent, 5.0 * time_fraction)
    agent.existential.novelty = min(1.0, agent.existential.novelty + 0.15)
    sim.adjust_emotion(agent, "curiosity_activation", -0.2)
    agent.bump_stat("explore_ticks")
    if rng.random() < wc.explore_discovery_probability:
        if rng.random() < 0.5:
            agent.tokens = round(agent.tokens + wc.explore_discovery_tokens, 4)
            what = f"{wc.explore_discovery_tokens:g} tokens"
        else:
            agent.food = min(sim.config.resources.maximum_food_inventory, agent.food + 1)
            what = "some wild food"
        agent.existential.novelty = min(1.0, agent.existential.novelty + 0.2)
        agent.bump_stat("discoveries")
        sim.emit("discovery", f"{agent.name} discovered {what} while exploring", agent=agent,
                 data={"found": what}, importance=0.6)
        sim.remember(agent, f"While exploring I discovered {what}.", kind="event", importance=0.5,
                     tags=["discovery"])
    if rng.random() < wc.explore_hazard_probability:
        sim.damage(agent, wc.hazard_damage, "hazard")
        sim.adjust_emotion(agent, "safety", -0.3)
        sim.emit("hazard", f"{agent.name} was hurt by a hazard while exploring", agent=agent,
                 data={"damage": wc.hazard_damage}, importance=0.7)
        sim.remember(agent, "I was injured by a hazard while exploring.", kind="event", importance=0.7,
                     tags=["danger"])
    return "continue"


def _tick_reflect(sim, agent, task, time_fraction):
    sim.spend_energy(agent, 1.0 * time_fraction)
    sim.adjust_emotion(agent, "stress", -0.12)
    agent.bump_stat("reflect_ticks")
    ex = agent.existential
    existential = bool(task.params.get("existential"))
    if existential:
        ex.ticks_contemplating += 1
        ex.reflections += 1
        sim.record_trait_evidence(agent, "spirituality", 1.0, 0.3)
    text = task.intention or (
        "I spent time contemplating why I exist and what my purpose might be."
        if existential else "I took time to think about my recent experiences."
    )
    sim.emit("reflect", f"{agent.name} reflected" + (" on existence" if existential else ""), agent=agent,
             data={"existential": existential, "intention": task.intention}, visibility="public",
             importance=0.3 if existential else 0.15)
    sim.remember(agent, text, kind="reflection", importance=0.5 if existential else 0.3,
                 tags=["existential"] if existential else ["reflection"])
    return "continue"


def _tick_create(sim, agent, task, time_fraction):
    sim.spend_energy(agent, 3.0 * time_fraction)
    agent.bump_stat("create_ticks")
    sim.adjust_emotion(agent, "happiness", 0.05)
    sim.adjust_emotion(agent, "stress", -0.05)
    if task.remaining_ticks <= 1:
        agent.artworks += 1
        sim.emit("create", f"{agent.name} finished a creative work", agent=agent,
                 data={"artworks": agent.artworks, "intention": task.intention}, importance=0.4)
        sim.remember(agent, task.intention or "I made something creative.", kind="event",
                     importance=0.4, tags=["creative"])
        sim.record_trait_evidence(agent, "artistic", 1.0, 0.4)
    return "continue"


def _tick_study(sim, agent, task, time_fraction):
    sim.spend_energy(agent, 3.0 * time_fraction)
    agent.knowledge = round(agent.knowledge + 1.0 * time_fraction, 3)
    agent.bump_stat("study_ticks")
    sim.adjust_emotion(agent, "curiosity_activation", -0.15)
    if task.remaining_ticks <= 1:
        sim.emit("study", f"{agent.name} studied (knowledge {agent.knowledge:.1f})", agent=agent,
                 data={"knowledge": agent.knowledge, "intention": task.intention}, importance=0.2)
        sim.record_trait_evidence(agent, "scientific_curiosity", 1.0, 0.4)
    return "continue"


def _work_energy(config) -> float:
    return config.work.energy_cost_per_tick


def register_core_actions() -> None:
    register(ActionSpec("idle", "Wait and do nothing for a tick.", _tick_idle))
    register(ActionSpec(
        "move", "Travel to a location or another agent.", _tick_move, target_kind="place",
        target_required=True, check=_check_move,
    ))
    register(ActionSpec(
        "work", "Work at a workplace to earn tokens. Costs energy; overwork and fatigue cost health.",
        _tick_work, location_type="workplace", target_kind="location",
        max_duration=lambda c: c.capacity.max_task_duration_ticks, default_duration=2,
        energy_per_tick=_work_energy, check=_check_work,
    ))
    register(ActionSpec(
        "eat", "Eat one meal: from your food inventory, or buy one at a food source.", _tick_eat,
        location_type="food", target_kind="location", check=_check_eat,
    ))
    register(ActionSpec(
        "buy_food", "Buy food to carry in your inventory (quantity).", _tick_buy_food,
        location_type="food", target_kind="location", check=_check_buy_food,
    ))
    register(ActionSpec(
        "rest", "Rest to recover energy (better at a rest area); health recovers if not hungry.",
        _tick_rest, max_duration=lambda c: c.capacity.max_rest_duration_ticks, default_duration=2,
    ))
    register(ActionSpec(
        "explore", "Wander into unfamiliar areas. May discover resources; small risk of injury.",
        _tick_explore, max_duration=3, energy_per_tick=_explore_energy,
    ))
    register(ActionSpec(
        "reflect", "Spend time thinking privately (about experiences, or existence and purpose).",
        _tick_reflect, max_duration=2, energy_per_tick=1.0,
    ))
    register(ActionSpec(
        "create", "Make something creative (art, a story, a song).", _tick_create,
        max_duration=3, default_duration=2, energy_per_tick=3.0,
    ))
    register(ActionSpec(
        "study", "Study the world and test ideas. Builds knowledge that slightly raises productivity.",
        _tick_study, max_duration=3, default_duration=2, energy_per_tick=3.0,
    ))


register_core_actions()

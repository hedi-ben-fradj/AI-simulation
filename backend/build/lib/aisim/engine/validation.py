"""Action validation: the gate between proposals and world state.

Order of checks follows the specification: liveness, time, energy, tokens,
attention, then action-specific world constraints. Durations outside the
allowed range are clamped (and noted) rather than rejected; anything that
would let an agent exceed its resources is rejected with a machine-readable
reason that is fed back to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .actions import REGISTRY, ActionProposal, at_location, distance, nearest_location, travel_ticks
from .communication import MessagePlan, plan_message
from .state import Agent, Task

if TYPE_CHECKING:  # pragma: no cover
    from .simulation import Simulation


@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None
    task: Task | None = None
    messages: list[MessagePlan] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _fail(reason: str, notes: list[str] | None = None) -> ValidationResult:
    return ValidationResult(False, reason, notes=notes or [])


def resolve_agent(sim: "Simulation", ref: str | None) -> Agent | None:
    if not ref:
        return None
    ref = str(ref).strip()
    agent = sim.world.agents.get(ref)
    if agent is not None:
        return agent
    low = ref.lower()
    for a in sim.world.agents.values():
        if a.name.lower() == low:
            return a
    return None


def resolve_location(sim: "Simulation", ref: str | None):
    if not ref:
        return None
    ref = str(ref).strip()
    loc = sim.world.locations.get(ref)
    if loc is not None:
        return loc
    low = ref.lower()
    for l in sim.world.locations.values():
        if l.name.lower() == low:
            return l
    return None


def validate_action(sim: "Simulation", agent: Agent, proposal: ActionProposal) -> ValidationResult:
    config = sim.config
    notes: list[str] = []

    if not agent.alive:
        return _fail("agent_is_dead")
    spec = REGISTRY.get((proposal.action or "").strip().lower())
    if spec is None or not spec.enabled(config):
        return _fail("unknown_action")

    task = Task(
        action=spec.name,
        started_tick=sim.world.tick,
        intention=(proposal.visible_intention or None),
        source=proposal.source,
    )

    # ---- duration --------------------------------------------------------
    max_d = spec.max_ticks(config)
    dur = proposal.duration if proposal.duration is not None else spec.default_duration
    try:
        dur = int(dur)
    except (TypeError, ValueError):
        dur = spec.default_duration
    if dur < spec.min_duration:
        dur = spec.min_duration
        notes.append("duration_raised")
    if dur > max_d:
        dur = max_d
        notes.append("duration_clamped")
    task.total_ticks = task.remaining_ticks = dur

    # ---- target ----------------------------------------------------------
    travel_energy = 0.0
    if spec.location_type:
        loc = resolve_location(sim, proposal.target) if proposal.target else nearest_location(sim, agent, spec.location_type)
        if proposal.target and loc is None:
            # The target may be an agent's name used loosely; fall back to nearest.
            loc = nearest_location(sim, agent, spec.location_type)
            notes.append("target_replaced_with_nearest")
        if loc is None:
            return _fail("no_such_location", notes)
        if loc.type != spec.location_type:
            return _fail("invalid_target", notes)
        task.target = loc.id
        if not at_location(agent, loc):
            task.travel_to = loc.id
            travel_energy = config.world.movement_speed_per_tick * config.world.movement_energy_per_unit
    elif spec.target_kind == "agent":
        other = resolve_agent(sim, proposal.target)
        if proposal.target and other is None:
            return _fail("invalid_target", notes)
        if other is None:
            if spec.target_required:
                return _fail("target_required", notes)
            if spec.location_fallback:
                loc = nearest_location(sim, agent, spec.location_fallback)
                if loc is not None:
                    task.target = None
                    if not at_location(agent, loc):
                        task.travel_to = loc.id
                        travel_energy = config.world.movement_speed_per_tick * config.world.movement_energy_per_unit
        else:
            if other.id == agent.id:
                return _fail("invalid_target", notes)
            if not other.alive:
                return _fail("target_dead", notes)
            task.target = other.id
            if spec.proximity and distance(agent.x, agent.y, other.x, other.y) > config.world.interaction_radius:
                task.travel_to = f"agent:{other.id}"
                travel_energy = config.world.movement_speed_per_tick * config.world.movement_energy_per_unit
    elif spec.target_kind == "place":
        loc = resolve_location(sim, proposal.target)
        other = resolve_agent(sim, proposal.target) if loc is None else None
        if loc is not None:
            task.target = loc.id
            task.travel_to = loc.id
            ticks = travel_ticks(sim, agent, loc.x, loc.y)
        elif other is not None and other.alive and other.id != agent.id:
            task.target = other.id
            task.travel_to = f"agent:{other.id}"
            ticks = travel_ticks(sim, agent, other.x, other.y, config.world.interaction_radius * 0.8)
        else:
            return _fail("invalid_target", notes)
        if ticks == 0:
            notes.append("already_there")
        travel_energy = min(1, ticks) * config.world.movement_speed_per_tick * config.world.movement_energy_per_unit
        task.total_ticks = task.remaining_ticks = 1
    elif spec.target_kind == "offer":
        if not proposal.target:
            return _fail("target_required", notes)
        task.target = str(proposal.target).strip()

    # ---- messages (planned now, sent when the decision is applied) -------
    message_plans: list[MessagePlan] = []
    wanted: list[tuple[str | None, str]] = []
    if proposal.message and proposal.message.strip():
        wanted.append((proposal.message_to or (task.target if spec.target_kind == "agent" else None),
                       proposal.message))
    for extra in proposal.extra_messages or []:
        if isinstance(extra, dict) and extra.get("content"):
            wanted.append((extra.get("to"), str(extra["content"])))
    if wanted and not config.communication.enabled:
        return _fail("communication_disabled", notes)
    for to_ref, content in wanted:
        recipient = resolve_agent(sim, to_ref)
        if recipient is None or recipient.id == agent.id:
            if spec.requires_message:
                return _fail("invalid_message_recipient", notes)
            notes.append("message_dropped_invalid_recipient")
            continue
        if not recipient.alive:
            notes.append("message_dropped_recipient_dead")
            continue
        if agent.messages_sent_this_tick + len(message_plans) >= agent.communication_capacity:
            if spec.requires_message and not message_plans:
                return _fail("communication_capacity_exceeded", notes)
            notes.append("message_dropped_capacity")
            continue
        plan = plan_message(sim, agent, recipient, content, len(message_plans))
        if plan.truncated:
            notes.append("message_truncated")
        message_plans.append(plan)

    # ---- time ------------------------------------------------------------
    available_time = 1.0 - agent.time_used_this_tick
    msg_time = sum(p.time_cost for p in message_plans)
    if msg_time > available_time + 1e-9:
        return _fail("insufficient_time", notes)

    # ---- energy (first tick of the commitment) ---------------------------
    first_tick_energy = travel_energy if task.travel_to else spec.energy_cost(config)
    first_tick_energy += sum(p.sender_energy for p in message_plans)
    if first_tick_energy > agent.energy + 1e-9:
        return _fail("insufficient_energy", notes)

    # ---- tokens ----------------------------------------------------------
    token_cost = sum(p.token_cost for p in message_plans)
    if token_cost > agent.tokens + 1e-9:
        return _fail("insufficient_tokens", notes)

    # ---- attention -------------------------------------------------------
    attention_cost = spec.attention_cost + sum(p.attention_cost for p in message_plans)
    if attention_cost > sim.attention_left(agent) + 1e-9:
        return _fail("insufficient_attention", notes)

    # ---- action-specific world constraints ------------------------------
    if spec.check is not None:
        reason = spec.check(sim, agent, proposal, task)
        if reason:
            return _fail(reason, notes)

    if spec.name == "reflect":
        from .existential import is_existential_text

        task.params["existential"] = bool(agent.existential.active or is_existential_text(proposal.visible_intention))

    return ValidationResult(True, None, task, message_plans, notes)

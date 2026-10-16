"""Decision-context builder.

Builds the per-decision user message from what the agent itself knows:

* its own state, personality, memories, relationships and observations;
* public facts about places (stock is only visible when nearby);
* other agents' *visible* behaviour (activity, apparent mood) when nearby,
  never their internal state or memories;
* messages and offers it actually read this tick (attention-limited).

The message never exceeds ``capacity.context_token_budget`` (estimated tokens).
When it would, sections are filled in a fixed priority order (spec 9.6):

1. survival-critical state          (always included)
2. current task, constraints, actions, places (always included)
3. recent events involving this decision
4. relationships and trust
5. durable memories
6. general historical summaries
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..engine.actions import REGISTRY, distance, nearest_location, travel_ticks
from ..engine.communication import estimate_tokens
from ..engine.state import TRAIT_DESCRIPTIONS
from .memory import retrieve
from .prompt import level_word

if TYPE_CHECKING:  # pragma: no cover
    from ..engine.simulation import DecisionRequest, Simulation
    from ..engine.state import Agent

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_text(text: str, limit: int = 400) -> str:
    """Neutralise other agents' text before it enters a prompt."""
    text = _CONTROL.sub(" ", text or "").replace('"', "'").strip()
    return text[:limit]


@dataclass
class Section:
    title: str
    lines: list[str]
    priority: int
    order: int
    required: bool = False
    omitted: int = 0

    def render(self) -> str:
        body = "\n".join(self.lines)
        if self.omitted:
            body += f"\n(+{self.omitted} older or less relevant item(s) omitted)"
        return f"{self.title}\n{body}"


@dataclass
class BuiltContext:
    text: str
    tokens: int
    sections: dict[str, int] = field(default_factory=dict)
    omitted: dict[str, int] = field(default_factory=dict)


def _emotion_text(agent: "Agent") -> str:
    e = agent.emotions
    parts = [f"mood {agent.current_mood}"]
    for key, label in (("stress", "stress"), ("happiness", "happiness"), ("loneliness", "loneliness"),
                       ("frustration", "frustration"), ("overload", "mental overload"), ("safety", "sense of safety")):
        parts.append(f"{label} {level_word(e.get(key, 0))}")
    return ", ".join(parts)


def _place_line(sim: "Simulation", agent: "Agent", loc) -> str:
    d = distance(agent.x, agent.y, loc.x, loc.y)
    here = d <= loc.radius
    ticks = travel_ticks(sim, agent, loc.x, loc.y, loc.radius * 0.5)
    where = "you are here" if here else f"{d:.0f} units away (~{ticks} tick{'s' if ticks != 1 else ''} to walk)"
    kind = {"workplace": "workplace", "food": "food source", "rest": "rest area", "gathering": "gathering place"}.get(
        loc.type, loc.type)
    extra = ""
    if loc.type == "food":
        visible = d <= sim.config.world.perception_radius
        stock = f"{loc.stock} meals in stock" if visible else "stock unknown from here"
        extra = f"; meal price {loc.price:g} tokens; {stock}"
    elif loc.type == "workplace":
        extra = f"; pays ~{sim.config.work.base_wage_per_tick * loc.wage_multiplier:g} tokens/tick"
    return f"- {loc.id} {loc.name} ({kind}): {where}{extra}"


def _action_lines(sim: "Simulation", agent: "Agent", request: "DecisionRequest") -> list[str]:
    cfg = sim.config
    lines = []
    food = nearest_location(sim, agent, "food")
    price = food.price if food and food.price is not None else cfg.resources.food_price
    known = [a for a in (sim.world.agents.get(r) for r in agent.relationships) if a is not None and a.alive]
    known_ids = ", ".join(f"{a.id} ({a.name})" for a in known[:10]) or "nobody yet"
    work_left = agent.work_capacity - agent.work_ticks_today
    for spec in REGISTRY.values():
        if not spec.enabled(cfg):
            continue
        max_d = spec.max_ticks(cfg)
        dur = f"; duration 1-{max_d} ticks" if max_d > 1 else ""
        note = ""
        if spec.name == "work":
            note = f" You can work {work_left} more tick(s) today." if work_left > 0 else " You cannot work more today."
        elif spec.name == "eat":
            if agent.food > 0:
                note = f" You carry {agent.food} meal(s)."
            else:
                note = (f" A meal costs {price:g} tokens; you have {agent.tokens:.1f}"
                        + ("." if agent.tokens >= price else " (not enough)."))
        elif spec.name in ("socialize", "talk", "give", "offer_trade", "steal"):
            note = f" Agents you know: {known_ids}."
        elif spec.name in ("accept_trade", "reject_trade") and not request.offers:
            continue  # nothing to respond to
        target = {
            "location": " [target: a place id, or null for the nearest]",
            "agent": " [target: an agent id]",
            "offer": " [target: an offer id]",
            "place": " [target: a place id or agent id]",
        }.get(spec.target_kind or "", "")
        lines.append(f"- {spec.name}{target}{dur}: {spec.description}{note}")
    return lines


def build_context(sim: "Simulation", request: "DecisionRequest") -> BuiltContext:
    cfg = sim.config
    agent = sim.world.agents[request.agent_id]
    tpd = cfg.simulation.ticks_per_day
    age_days = (sim.world.tick - agent.born_tick) / tpd
    here = next((l for l in sim.world.locations.values()
                 if distance(agent.x, agent.y, l.x, l.y) <= l.radius), None)
    nearby = sim.agents_within(agent, cfg.world.perception_radius)
    sections: list[Section] = []

    # ---- 1. identity + survival-critical state ---------------------------
    sections.append(Section("IDENTITY", [
        f"Your name is {agent.name} (id {agent.id}).",
        f"Your age is {age_days:.1f} days.",
        f"Your background: {agent.name} {agent.background}.",
    ], priority=1, order=0, required=True))
    situation = [
        f"Time: {sim.time_label()}",
        f"Location: {here.name + ' (' + here.id + ')' if here else f'open ground at ({agent.x:.0f}, {agent.y:.0f})'}",
        f"Health: {agent.health:.0f}/{cfg.resources.maximum_health:g}",
        f"Energy: {agent.energy:.0f}/{cfg.resources.maximum_energy:g}",
        f"Hunger: {agent.hunger:.0f}/{cfg.resources.maximum_hunger:g}"
        + (" - CRITICAL, you are losing health" if agent.hunger >= cfg.resources.critical_hunger else ""),
        f"Money: {agent.tokens:.1f} tokens",
        f"Inventory: {agent.food} meal(s) of food" + (f"; knowledge {agent.knowledge:.1f}" if agent.knowledge else ""),
        f"Available time: {max(0.0, 1 - agent.time_used_this_tick):.2f} of this tick; "
        f"work capacity left today: {agent.work_capacity - agent.work_ticks_today} tick(s)",
        f"Current emotional state: {_emotion_text(agent)}",
    ]
    if request.last_failure:
        situation.append(f"Your last attempt failed: {request.last_failure}.")
    active_goals = [g for g in request.goals if g["active"]]
    if active_goals:
        situation.append("Most pressing goals: " + "; ".join(f"{g['id']} ({g['label'].lower()})" for g in active_goals))
    if request.existential_active:
        situation.append("A question about your own existence and purpose feels unusually present for you right now. "
                         "You may engage with it, or set it aside if other needs are more pressing.")
    if request.overload > 0:
        situation.append(f"You feel overloaded: {request.unread_messages} message(s) remain unread.")
    sections.append(Section("CURRENT SITUATION", situation, priority=1, order=1, required=True))

    traits = sorted(agent.personality.items(), key=lambda kv: -abs(kv[1] - 0.5))
    sections.append(Section("PERSONALITY", [
        "Tendencies, not rules (0 = very low, 1 = very high):",
        *[f"- {t.replace('_', ' ')}: {level_word(v)} ({v:.2f}) - {TRAIT_DESCRIPTIONS[t]}" for t, v in traits],
    ], priority=1, order=2, required=True))

    # ---- 2. constraints of the current decision --------------------------
    world_lines = ["Places:"] + [_place_line(sim, agent, l) for l in sim.world.locations.values()]
    if nearby:
        world_lines.append("People you can see nearby (only what is visible):")
        for o in sorted(nearby, key=lambda o: distance(agent.x, agent.y, o.x, o.y)):
            name = o.name if o.id in agent.relationships else "someone you have not met"
            world_lines.append(f"- {o.id} {name}: {distance(agent.x, agent.y, o.x, o.y):.0f} units away, "
                               f"{'travelling' if o.current_task and o.current_task.travel_to else o.current_action}, "
                               f"looks {o.current_mood}")
    else:
        world_lines.append("Nobody is within sight.")
    sections.append(Section("WORLD CONDITIONS", world_lines, priority=2, order=7, required=True))

    actions = _action_lines(sim, agent, request)
    if request.offers:
        actions.append("Offers waiting for your answer:")
        for o in request.offers:
            what_in = ", ".join(f"{v:g} {k}" for k, v in o.offer.items()) or "nothing"
            what_out = ", ".join(f"{v:g} {k}" for k, v in o.request.items()) or "nothing"
            note = f' Note: "{clean_text(o.note, 160)}"' if o.note else ""
            actions.append(f"- offer {o.id} from {o.from_id} {clean_text(o.from_name, 40)}: they give {what_in}, "
                           f"they want {what_out}; expires in {o.expires_tick - sim.world.tick} tick(s).{note}")
    sections.append(Section("AVAILABLE ACTIONS", actions, priority=2, order=8, required=True))

    # ---- 3. recent events ------------------------------------------------
    recent: list[str] = []
    for m in request.messages:
        recent.append(f'- [tick {m.sent_tick}] {clean_text(m.sender_name, 40)} ({m.sender_id}) said to you: "{clean_text(m.content)}"')
    for obs in reversed(request.observations):
        if obs.kind == "message":
            continue
        recent.append(f"- [tick {obs.tick}] {clean_text(obs.text)}")
    if not recent:
        recent.append("- Nothing new since your last decision.")
    sections.append(Section("RECENT EXPERIENCES", recent, priority=3, order=4))

    # ---- 4. relationships --------------------------------------------------
    involved = {m.sender_id for m in request.messages} | {o.from_id for o in request.offers} | {o.id for o in nearby}
    for obs in request.observations:
        involved |= set(obs.related_agents)
    rels = sorted(agent.relationships.values(),
                  key=lambda r: (r.other_id not in involved, -r.familiarity, r.other_id))
    rel_lines = []
    for r in rels:
        other = sim.world.agents.get(r.other_id)
        status = "" if other is None or other.alive else " (dead)"
        inter = ", ".join(f"{k} {v}" for k, v in sorted(r.interactions.items())) or "no interactions yet"
        rel_lines.append(f"- {r.other_id} {r.other_name}{status}: your trust {r.trust:.2f}, "
                         f"familiarity {r.familiarity}, warmth {r.affinity:+.2f}; {inter}")
    if not rel_lines:
        rel_lines.append("- You do not know anyone yet.")
    sections.append(Section("RELATIONSHIPS", rel_lines, priority=4, order=5))

    # ---- 5. memories -------------------------------------------------------
    mems = retrieve(sim, agent, involved, request.existential_active, limit=15)
    mem_lines = [f"- [day {m.tick // tpd + 1}] ({m.kind}) {clean_text(m.content, 240)}" for m in mems]
    if agent.existential.beliefs:
        mem_lines.insert(0, f"- Your current view on your purpose: {clean_text(agent.existential.beliefs[-1]['text'], 300)}")
    if not mem_lines:
        mem_lines.append("- No notable memories yet.")
    sections.append(Section("MEMORIES", mem_lines, priority=5, order=3))

    # ---- 6. history ----------------------------------------------------------
    if agent.life_summary:
        sections.append(Section("EARLIER LIFE (summary)", [f"- {s}" for s in reversed(agent.life_summary)],
                                priority=6, order=6))

    return _fit(sections, cfg.capacity.context_token_budget)


def _fit(sections: list[Section], budget: int) -> BuiltContext:
    used = sum(estimate_tokens(s.render()) + 1 for s in sections if s.required)
    for s in sorted((s for s in sections if not s.required), key=lambda s: s.priority):
        remaining = budget - used
        while s.lines and estimate_tokens(s.render()) + 1 > remaining:
            s.lines.pop()
            s.omitted += 1
        if s.lines:
            used += estimate_tokens(s.render()) + 1
    kept = [s for s in sorted(sections, key=lambda s: s.order) if s.lines]
    text = "\n\n".join(s.render() for s in kept)
    return BuiltContext(
        text=text, tokens=estimate_tokens(text),
        sections={s.title: estimate_tokens(s.render()) for s in kept},
        omitted={s.title: s.omitted for s in sections if s.omitted},
    )

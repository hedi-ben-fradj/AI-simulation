"""The authoritative simulation engine.

A tick proceeds in three steps, which lets an asynchronous orchestrator obtain
LLM decisions between them without the engine ever depending on the LLM:

1. ``begin_tick()``  - deliver messages, expire offers, allocate attention,
   sample existential activation and return a :class:`DecisionRequest` for
   every agent that needs a new decision.
2. ``apply_decisions(proposals)`` - validate each proposal against the
   *current* state; invalid or missing proposals get a rule-based fallback.
3. ``advance()`` - execute one tick of every committed task, apply needs,
   deaths, observations and daily rules, collect metrics, and return a
   :class:`TickResult` with everything that should be persisted.

``step()`` runs all three synchronously with the rule-based policy, which is
what tests and headless experiments use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import SimulationConfig
from . import existential as ex_mod
from . import personality as pers_mod
from . import trust as trust_mod
from .actions import (
    ARRIVAL_TOLERANCE,
    REGISTRY,
    ActionProposal,
    current_location,
    distance,
    step_towards,
)
from .events import Event
from .goals import compute_goals
from .metrics import compute_metrics
from .rng import RandomStreams
from .state import Agent, Memory, Message, Observation, Relationship, Task, TradeOffer, WorldState
from .validation import ValidationResult, validate_action
from .worldgen import create_agent, generate_world

MAX_TRAVEL_TICKS = 8


@dataclass
class DecisionRequest:
    agent_id: str
    tick: int
    controller: str
    messages: list[Message] = field(default_factory=list)
    unread_messages: int = 0
    offers: list[TradeOffer] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    goals: list[dict[str, Any]] = field(default_factory=list)
    existential_active: bool = False
    existential_probability: float = 0.0
    overload: float = 0.0
    attention_budget: float = 0.0
    attention_left: float = 0.0
    last_failure: str | None = None


@dataclass
class DecisionRecord:
    tick: int
    agent_id: str
    source: str
    proposal: dict[str, Any]
    valid: bool
    reason: str | None = None
    notes: list[str] = field(default_factory=list)
    visible_intention: str | None = None
    existential_active: bool = False
    applied_action: str | None = None
    fallback_reason: str | None = None
    latency_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class TickResult:
    tick: int
    events: list[Event] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    memories: list[tuple[str, Memory]] = field(default_factory=list)
    trait_changes: list[dict[str, Any]] = field(default_factory=list)
    trust_changes: list[dict[str, Any]] = field(default_factory=list)
    deaths: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    # (message id, tick) for every message an agent read this tick.
    reads: list[tuple[str, int]] = field(default_factory=list)


class Simulation:
    def __init__(self, config: SimulationConfig, world: WorldState, streams: RandomStreams):
        self.config = config
        self.world = world
        self.streams = streams
        self._pending: dict[str, DecisionRequest] = {}
        self._attention_left: dict[str, float] = {}
        # What each agent actually did during the current tick (for needs/metrics).
        self.executed: dict[str, str] = {}
        self._result = TickResult(tick=world.tick)
        self._tick_open = False

    # ------------------------------------------------------------------
    # Construction and snapshots
    # ------------------------------------------------------------------
    @classmethod
    def create(cls, config: SimulationConfig, world_id: str | None = None) -> "Simulation":
        world, streams = generate_world(config, world_id)
        return cls(config, world, streams)

    @classmethod
    def from_snapshot(cls, config: SimulationConfig, snapshot: dict[str, Any]) -> "Simulation":
        world = WorldState.model_validate(snapshot)
        streams = RandomStreams.from_state(world.rng_state) if world.rng_state else RandomStreams(
            config.simulation.random_seed)
        return cls(config, world, streams)

    def snapshot(self) -> dict[str, Any]:
        self.world.rng_state = self.streams.to_state()
        return self.world.model_dump(mode="json")

    # ------------------------------------------------------------------
    # Time
    # ------------------------------------------------------------------
    @property
    def tick(self) -> int:
        return self.world.tick

    @property
    def day(self) -> int:
        return self.world.tick // self.config.simulation.ticks_per_day

    def time_label(self, tick: int | None = None) -> str:
        tick = self.world.tick if tick is None else tick
        tpd = self.config.simulation.ticks_per_day
        minutes = int(round((tick % tpd) * 24 * 60 / tpd))
        return f"Day {tick // tpd + 1}, {minutes // 60:02d}:{minutes % 60:02d}"

    # ------------------------------------------------------------------
    # Helpers used by action handlers
    # ------------------------------------------------------------------
    def emit(self, type_: str, summary: str, agent: Agent | None = None, target: str | None = None,
             data: dict[str, Any] | None = None, visibility: str = "public",
             participants: list[str] | None = None, importance: float = 0.3) -> Event:
        participants = list(participants or [])
        if agent is not None and agent.id not in participants and visibility == "private":
            participants.insert(0, agent.id)
        event = Event(
            tick=self.world.tick, type=type_, summary=summary,
            agent_id=agent.id if agent else None, target_id=target, data=data or {},
            visibility=visibility, participants=participants,
            x=round(agent.x, 2) if agent else None, y=round(agent.y, 2) if agent else None,
            importance=importance,
        )
        self._result.events.append(event)
        return event

    def spend_energy(self, agent: Agent, amount: float) -> None:
        agent.energy = round(max(0.0, agent.energy - amount), 4)

    def damage(self, agent: Agent, amount: float, cause: str) -> None:
        if amount <= 0:
            return
        agent.health = round(max(0.0, agent.health - amount), 4)
        agent.last_damage_cause = cause
        agent.bump_stat(f"damage_{cause}", amount)

    def adjust_emotion(self, agent: Agent, name: str, delta: float) -> None:
        agent.emotions[name] = round(max(0.0, min(1.0, agent.emotion(name) + delta)), 4)

    def productivity(self, agent: Agent) -> float:
        wc = self.config.work
        p = wc.low_energy_productivity if agent.energy < wc.fatigue_energy_threshold else 1.0
        p *= 1 + min(wc.max_productivity_bonus, agent.knowledge * wc.knowledge_productivity_per_point)
        if agent.health < 50:
            p *= 0.8
        return p

    def need_pressure(self, agent: Agent) -> float:
        rc = self.config.resources
        price = rc.food_price
        parts = [agent.hunger / max(1.0, rc.critical_hunger)]
        if agent.energy < 40:
            parts.append((40 - agent.energy) / 40)
        if agent.tokens < 2 * price and agent.food == 0:
            parts.append(1 - agent.tokens / (2 * price))
        if agent.health < 50:
            parts.append((50 - agent.health) / 50)
        return max(0.0, min(1.0, max(parts)))

    def agents_within(self, agent: Agent, radius: float) -> list[Agent]:
        return [
            o for o in self.world.agents.values()
            if o.alive and o.id != agent.id and distance(agent.x, agent.y, o.x, o.y) <= radius + 1e-6
        ]

    def attention_left(self, agent: Agent) -> float:
        return self._attention_left.get(agent.id, agent.attention_capacity)

    def relationship(self, agent: Agent, other: Agent) -> Relationship:
        rel = agent.relationships.get(other.id)
        if rel is None:
            rel = trust_mod.new_relationship(self.config.trust, other, self.world.tick)
            agent.relationships[other.id] = rel
        return rel

    def trust_evidence(self, truster: Agent, trustee: Agent, positive: bool, weight: float, reason: str) -> None:
        rel = self.relationship(truster, trustee)
        before, after = trust_mod.apply_evidence(self.config.trust, rel, positive, weight)
        rel.last_interaction_tick = self.world.tick
        self._result.trust_changes.append({
            "tick": self.world.tick, "agent_id": truster.id, "other_id": trustee.id, "reason": reason,
            "positive": positive, "weight": round(min(weight, self.config.trust.maximum_evidence_weight), 4),
            "trust_before": round(before, 4), "trust_after": round(after, 4),
        })

    def record_trait_evidence(self, agent: Agent, trait: str, target: float, weight: float) -> None:
        pers_mod.add_evidence(agent, trait, target, weight)

    def observe(self, agent: Agent, kind: str, text: str, related: list[str] | None = None,
                importance: float = 0.3) -> None:
        agent.short_term.append(Observation(tick=self.world.tick, kind=kind, text=text,
                                            related_agents=related or [], importance=importance))
        cap = self.config.capacity.short_term_capacity
        if len(agent.short_term) > cap:
            del agent.short_term[: len(agent.short_term) - cap]

    def remember(self, agent: Agent, content: str, kind: str = "event", importance: float = 0.5,
                 related: list[str] | None = None, tags: list[str] | None = None,
                 source: str = "engine") -> Memory:
        memory = Memory(id=self.world.next_id("m"), tick=self.world.tick, kind=kind, content=content[:400],
                        importance=round(max(0.0, min(1.0, importance)), 3), related_agents=related or [],
                        tags=tags or [], source=source)
        agent.memories.append(memory)
        self._result.memories.append((agent.id, memory))
        self._consolidate_memories(agent)
        return memory

    def _consolidate_memories(self, agent: Agent) -> None:
        cap = self.config.capacity.max_memories_per_agent
        if len(agent.memories) <= cap:
            return
        # Drop the least valuable memories (low importance, old); they remain
        # in the persistent store and in day summaries but leave working memory.
        now = self.world.tick
        tpd = self.config.simulation.ticks_per_day

        def value(m: Memory) -> float:
            age_days = (now - m.tick) / tpd
            return m.importance - 0.05 * age_days

        keep = sorted(agent.memories, key=value, reverse=True)[: cap - 1]
        keep_ids = {m.id for m in keep}
        dropped = [m for m in agent.memories if m.id not in keep_ids]
        agent.memories = [m for m in agent.memories if m.id in keep_ids]
        # Fold what leaves working memory into one compact summary memory.
        first, last = min(m.tick for m in dropped) // tpd + 1, max(m.tick for m in dropped) // tpd + 1
        span = f"day {first}" if first == last else f"days {first}-{last}"
        gist = "; ".join(m.content.rstrip(".") for m in sorted(dropped, key=lambda m: -m.importance)[:4])
        related = sorted({r for m in dropped for r in m.related_agents})[:6]
        tags = sorted({t for m in dropped for t in m.tags})[:6]
        summary = Memory(id=self.world.next_id("m"), tick=max(m.tick for m in dropped), kind="summary",
                         content=f"Older memories ({span}): {gist}."[:400],
                         importance=round(min(0.9, max(m.importance for m in dropped) * 0.8), 3),
                         related_agents=related, tags=tags + ["summary"])
        agent.memories.append(summary)
        self._result.memories.append((agent.id, summary))

    def create_trade_offer(self, sender: Agent, recipient: Agent, offer: dict[str, float],
                           request: dict[str, float], note: str | None = None) -> TradeOffer:
        trade = TradeOffer(
            id=self.world.next_id("t"), from_id=sender.id, from_name=sender.name, to_id=recipient.id,
            offer=offer, request=request, created_tick=self.world.tick,
            expires_tick=self.world.tick + self.config.social.trade_offer_expiry_ticks, note=(note or None),
        )
        self.world.trade_offers[trade.id] = trade
        return trade

    # ------------------------------------------------------------------
    # Tick step 1: begin
    # ------------------------------------------------------------------
    def begin_tick(self) -> list[DecisionRequest]:
        if self._tick_open:
            return list(self._pending.values())
        self._tick_open = True
        self._result = TickResult(tick=self.world.tick)
        self._pending = {}
        self._attention_left = {}
        self.executed = {}
        world = self.world
        world.messages_this_tick = 0
        for loc in world.locations.values():
            loc.occupancy = 0
        for agent in world.agents.values():
            agent.messages_sent_this_tick = 0
            agent.time_used_this_tick = 0.0
        self._deliver_messages()
        self._expire_offers()
        for agent in sorted(world.alive_agents(), key=lambda a: a.id):
            if agent.current_task is None:
                self._pending[agent.id] = self._prepare_decision(agent)
        return list(self._pending.values())

    def pending_requests(self) -> list[DecisionRequest]:
        return list(self._pending.values())

    def _deliver_messages(self) -> None:
        cc = self.config.capacity
        world = self.world
        still: list[Message] = []
        for msg in world.in_flight_messages:
            if msg.deliver_tick > world.tick:
                still.append(msg)
                continue
            recipient = world.agents.get(msg.recipient_id)
            if recipient is None or not recipient.alive:
                continue
            recipient.inbox.append(msg)
            if len(recipient.inbox) > cc.inbox_capacity:
                dropped = recipient.inbox.pop(0)
                self.emit("message_dropped", f"A message to {recipient.name} was dropped (inbox full)",
                          agent=recipient, data={"message_id": dropped.id, "reason": "inbox_full"},
                          visibility="system", importance=0.1)
        world.in_flight_messages = still
        for agent in world.alive_agents():
            before = len(agent.inbox)
            expired = [m.id for m in agent.inbox if world.tick - m.deliver_tick > cc.message_expiry_ticks]
            agent.inbox = [m for m in agent.inbox if world.tick - m.deliver_tick <= cc.message_expiry_ticks]
            if len(agent.inbox) < before:
                self.emit("message_expired", f"{before - len(agent.inbox)} unread message(s) expired for {agent.name}",
                          agent=agent, data={"count": before - len(agent.inbox), "message_ids": expired},
                          visibility="system", importance=0.1)

    def _expire_offers(self) -> None:
        for offer in self.world.trade_offers.values():
            if offer.status == "pending" and offer.expires_tick <= self.world.tick:
                offer.status = "expired"
                proposer = self.world.agents.get(offer.from_id)
                if proposer is not None and proposer.alive:
                    self.observe(proposer, "offer_expired", "One of my offers expired without an answer.",
                                 related=[offer.to_id], importance=0.3)
        # Keep the table bounded: forget resolved offers after a while.
        horizon = self.world.tick - 4 * self.config.simulation.ticks_per_day
        self.world.trade_offers = {
            k: v for k, v in self.world.trade_offers.items() if v.status == "pending" or v.created_tick > horizon
        }

    def _prepare_decision(self, agent: Agent) -> DecisionRequest:
        cc = self.config.capacity
        budget = agent.attention_capacity
        left = budget - cc.decision_attention_cost
        demand = cc.decision_attention_cost

        goals = compute_goals(self, agent)
        agent.goals = goals
        active_goals = [g for g in goals if g["active"]]
        goal_cost = 0.5 * max(0, len(active_goals) - 1)
        demand += goal_cost
        left -= goal_cost

        offers = sorted(
            (o for o in self.world.trade_offers.values() if o.to_id == agent.id and o.status == "pending"),
            key=lambda o: (o.created_tick, o.id),
        )
        attended_offers = []
        for offer in offers:
            demand += cc.offer_attention_cost
            if left >= cc.offer_attention_cost:
                left -= cc.offer_attention_cost
                attended_offers.append(offer)

        read: list[Message] = []
        unread = sorted(agent.inbox, key=lambda m: (m.deliver_tick, m.id))
        for msg in unread:
            demand += cc.message_attention_cost
            if len(read) < cc.max_incoming_messages_processed_per_tick and left >= cc.message_attention_cost:
                left -= cc.message_attention_cost
                read.append(msg)
        read_ids = {m.id for m in read}
        agent.inbox = [m for m in agent.inbox if m.id not in read_ids]
        for msg in read:
            self._read_message(agent, msg)

        recent = [o for o in agent.short_term if o.tick >= agent.last_decision_tick]
        recent.sort(key=lambda o: (-o.importance, -o.tick))
        attended_obs = []
        for obs in recent:
            demand += cc.observation_attention_cost
            if left >= cc.observation_attention_cost:
                left -= cc.observation_attention_cost
                attended_obs.append(obs)
        attended_obs.sort(key=lambda o: o.tick)

        left = max(0.0, left)
        overload = max(0.0, min(1.0, (demand - budget) / budget)) if budget > 0 else 1.0
        agent.emotions["overload"] = round(max(agent.emotion("overload") * 0.5, overload), 4)
        self._attention_left[agent.id] = left

        rc = self.config.resources
        needs_ok = agent.hunger < rc.health_recovery_max_hunger and agent.energy > 40
        active, prob = False, 0.0
        if self.config.existential_goal.enabled:
            inputs = ex_mod.activation_inputs(agent, left / budget if budget > 0 else 0.0, needs_ok)
            prob = ex_mod.activation_probability(self.config.existential_goal, **inputs)
            active = self.streams["existential"].random() < prob
            agent.existential.opportunities += 1
            agent.existential.last_probability = round(prob, 5)
            if active:
                agent.existential.activations += 1
                self.emit("existential_activation", f"A question about existence became salient for {agent.name}",
                          agent=agent, data={"probability": round(prob, 4), "inputs": {k: round(v, 3) for k, v in inputs.items()}},
                          visibility="system", importance=0.2)
        agent.existential.active = active
        if active:
            for g in agent.goals:
                if g["id"] == "existential":
                    g["salience"] = max(g["salience"], 0.6)
                    g["active"] = True

        return DecisionRequest(
            agent_id=agent.id, tick=self.world.tick, controller=agent.controller, messages=read,
            unread_messages=len(agent.inbox), offers=attended_offers, observations=attended_obs,
            goals=agent.goals, existential_active=active, existential_probability=prob,
            overload=overload, attention_budget=budget, attention_left=left,
            last_failure=agent.last_failure,
        )

    def _read_message(self, agent: Agent, msg: Message) -> None:
        cc = self.config.communication
        msg.read_tick = self.world.tick
        self._result.reads.append((msg.id, self.world.tick))
        self.spend_energy(agent, cc.receiver_energy_per_token * msg.tokens)
        sender = self.world.agents.get(msg.sender_id)
        if sender is not None:
            rel = self.relationship(agent, sender)
            rel.interactions["message_received"] = rel.interactions.get("message_received", 0) + 1
            rel.last_interaction_tick = self.world.tick
        self.observe(agent, "message", f'{msg.sender_name} said: "{msg.content}"', related=[msg.sender_id],
                     importance=0.6)
        if msg.existential:
            agent.existential.discussion_exposure = min(1.0, agent.existential.discussion_exposure + 0.4)
        agent.bump_stat("messages_read")

    # ------------------------------------------------------------------
    # Tick step 2: decisions
    # ------------------------------------------------------------------
    def apply_decisions(self, proposals: dict[str, ActionProposal],
                        meta: dict[str, dict[str, Any]] | None = None,
                        fallback: Callable[["Simulation", DecisionRequest], ActionProposal] | None = None
                        ) -> list[DecisionRecord]:
        from .policy import decide as rule_decide

        fallback = fallback or rule_decide
        meta = meta or {}
        records = []
        for agent_id in sorted(self._pending):
            request = self._pending[agent_id]
            agent = self.world.agents[agent_id]
            info = meta.get(agent_id, {})
            proposal = proposals.get(agent_id)
            if proposal is None:
                reason = info.get("fallback_reason", "no_decision")
                fb = fallback(self, request)
                fb.source = "fallback"
                records.append(self._commit(agent, request, fb, fallback_reason=reason,
                                            latency_ms=info.get("latency_ms")))
                continue
            record = self._commit(agent, request, proposal, latency_ms=info.get("latency_ms"))
            records.append(record)
        self._pending = {}
        return records

    def _commit(self, agent: Agent, request: DecisionRequest, proposal: ActionProposal,
                fallback_reason: str | None = None, latency_ms: float | None = None) -> DecisionRecord:
        from .policy import decide as rule_decide

        result = validate_action(self, agent, proposal)
        record = DecisionRecord(
            tick=self.world.tick, agent_id=agent.id, source=proposal.source,
            proposal=proposal.model_dump(exclude_none=True), valid=result.ok, reason=result.reason,
            notes=result.notes, visible_intention=proposal.visible_intention,
            existential_active=request.existential_active, fallback_reason=fallback_reason,
            latency_ms=latency_ms,
        )
        if not result.ok:
            agent.last_failure = f"{proposal.action}: {result.reason}"
            self.adjust_emotion(agent, "frustration", 0.1)
            agent.existential.uncertainty = min(1.0, agent.existential.uncertainty + 0.03)
            self.observe(agent, "failure", f"My attempt to {proposal.action} was not possible ({result.reason}).",
                         importance=0.5)
            self.emit("action_rejected", f"{agent.name}'s proposal '{proposal.action}' was rejected: {result.reason}",
                      agent=agent, data={"proposal": record.proposal, "reason": result.reason},
                      visibility="system", importance=0.2)
            fb = rule_decide(self, request, avoid=proposal.action)
            fb.source = "fallback"
            result = validate_action(self, agent, fb)
            if not result.ok:
                result = validate_action(self, agent, ActionProposal(action="idle", source="fallback",
                                                                     visible_intention="Waiting."))
            record.fallback_reason = record.fallback_reason or "invalid_proposal"
        else:
            agent.last_failure = None
        assert result.task is not None
        # Memory candidates and beliefs are cognitive output: kept even when the
        # physical action had to be replaced.
        self._start_task(agent, result, proposal)
        record.applied_action = result.task.action
        self._result.decisions.append(record)
        return record

    def _start_task(self, agent: Agent, result: ValidationResult, proposal: ActionProposal) -> None:
        task = result.task
        agent.current_task = task
        agent.current_action = task.action
        agent.visible_intention = task.intention
        agent.last_decision_tick = self.world.tick
        if task.intention:
            agent.active_intentions = ([task.intention] + [i for i in agent.active_intentions if i != task.intention])[
                : self.config.capacity.max_active_goals]
        agent.recent_actions = (agent.recent_actions + [task.action])[-8:]
        for plan in result.messages:
            self._send_message(agent, plan)
        self._store_memory_candidates(agent, proposal)
        if proposal.belief:
            self._record_belief(agent, proposal.belief)

    def _send_message(self, agent: Agent, plan) -> None:
        cc = self.config.communication
        recipient = self.world.agents[plan.recipient_id]
        agent.tokens = round(agent.tokens - plan.token_cost, 5)
        self.spend_energy(agent, plan.sender_energy)
        agent.time_used_this_tick += plan.time_cost
        agent.messages_sent_this_tick += 1
        self._attention_left[agent.id] = max(0.0, self.attention_left(agent) - plan.attention_cost)
        self.world.messages_this_tick += 1
        existential = ex_mod.is_existential_text(plan.content)
        msg = Message(
            id=self.world.next_id("msg"), sender_id=agent.id, sender_name=agent.name, recipient_id=recipient.id,
            content=plan.content, tokens=plan.tokens, sent_tick=self.world.tick,
            deliver_tick=self.world.tick + cc.delivery_delay_ticks, token_cost=plan.token_cost,
            existential=existential,
        )
        self.world.in_flight_messages.append(msg)
        self._result.messages.append(msg)
        rel = self.relationship(agent, recipient)
        rel.interactions["message_sent"] = rel.interactions.get("message_sent", 0) + 1
        agent.bump_stat("messages_sent")
        agent.bump_stat("communication_token_cost", plan.token_cost)
        if existential:
            agent.existential.conversations += 1
        self.emit("message", f'{agent.name} → {recipient.name}: "{plan.content}"', agent=agent,
                  target=recipient.id,
                  data={"message_id": msg.id, "tokens": plan.tokens, "token_cost": plan.token_cost,
                        "time_cost": plan.time_cost, "existential": existential},
                  visibility="private", participants=[agent.id, recipient.id], importance=0.35)

    def _store_memory_candidates(self, agent: Agent, proposal: ActionProposal) -> None:
        for cand in (proposal.memory_candidates or [])[:2]:
            if isinstance(cand, str):
                content, importance = cand, 0.5
            elif isinstance(cand, dict) and cand.get("content"):
                content = str(cand["content"])
                try:
                    importance = float(cand.get("importance", 0.5))
                except (TypeError, ValueError):
                    importance = 0.5
            else:
                continue
            content = content.strip()[:240]
            if not content:
                continue
            # Self-assessed importance is capped so agents cannot flood memory with "critical" notes.
            self.remember(agent, content, kind="note", importance=min(0.8, importance), source="agent",
                          tags=["existential"] if ex_mod.is_existential_text(content) else [])

    def _record_belief(self, agent: Agent, belief: str) -> None:
        belief = belief.strip()[:300]
        if not belief:
            return
        beliefs = agent.existential.beliefs
        previous = beliefs[-1]["text"] if beliefs else None
        if previous == belief:
            return
        beliefs.append({"tick": self.world.tick, "text": belief})
        del beliefs[:-10]
        self.remember(agent, f"My current belief about my purpose: {belief}", kind="belief", importance=0.7,
                      source="agent", tags=["existential", "belief"])
        self.emit("belief_update", f"{agent.name} {'revised' if previous else 'formed'} a belief about purpose",
                  agent=agent, data={"belief": belief, "previous": previous}, visibility="system", importance=0.4)

    # ------------------------------------------------------------------
    # Tick step 3: advance
    # ------------------------------------------------------------------
    def advance(self) -> TickResult:
        if not self._tick_open:
            self.begin_tick()
        if self._pending:
            self.apply_decisions({})
        world = self.world
        order = sorted(world.alive_agents(), key=lambda a: a.id)
        self.streams["order"].shuffle(order)
        for agent in order:
            if agent.alive:
                self._run_task(agent)
        for agent in sorted(world.alive_agents(), key=lambda a: a.id):
            self._update_needs(agent)
        self._ambient_hazards()
        for agent in sorted(world.alive_agents(), key=lambda a: a.id):
            self._check_death(agent)
        self._detect_meetings()
        self._propagate_observations()
        if (world.tick + 1) % self.config.simulation.ticks_per_day == 0:
            self._end_of_day()
        if (world.tick + 1) % self.config.personality.update_interval_ticks == 0:
            for agent in sorted(world.alive_agents(), key=lambda a: a.id):
                changes = pers_mod.apply_accumulated(self.config.personality, agent, world.tick)
                self._result.trait_changes.extend(changes)
                for ch in changes:
                    self.emit("trait_change", f"{agent.name}'s {ch['trait']} changed {ch['old']:.3f} → {ch['new']:.3f}",
                              agent=agent, data=ch, visibility="system", importance=0.2)
        self._result.metrics = compute_metrics(self, self._result)
        result = self._result
        world.tick += 1
        self._tick_open = False
        return result

    def step(self, decider: Callable[["Simulation", DecisionRequest], ActionProposal] | None = None) -> TickResult:
        from .policy import decide as rule_decide

        decider = decider or rule_decide
        requests = self.begin_tick()
        proposals = {r.agent_id: decider(self, r) for r in requests}
        self.apply_decisions(proposals)
        return self.advance()

    def _run_task(self, agent: Agent) -> None:
        task = agent.current_task
        if task is None:
            agent.time_allocation["idle"] = agent.time_allocation.get("idle", 0) + 1
            self.executed[agent.id] = "idle"
            return
        self.executed[agent.id] = "travel" if task.travel_to else task.action
        time_fraction = max(0.0, 1.0 - agent.time_used_this_tick)
        if task.travel_to:
            x0, y0 = agent.x, agent.y
            arrived, moved = self._travel(agent, task)
            if not arrived:
                agent.time_allocation["travel"] = agent.time_allocation.get("travel", 0) + 1
                task.params["travel_ticks"] = task.params.get("travel_ticks", 0) + 1
                if task.params["travel_ticks"] >= MAX_TRAVEL_TICKS:
                    self._fail_task(agent, task, "could_not_reach_target")
                return
            task.travel_to = None
            if task.action == "move":
                agent.time_allocation["travel"] = agent.time_allocation.get("travel", 0) + 1
                self._finish_task(agent, task)
                loc = current_location(self, agent)
                self.emit("arrive", f"{agent.name} arrived at {loc.name if loc else 'destination'}", agent=agent,
                          data={"location": loc.id if loc else None}, importance=0.05)
                return
            if moved:
                # Arriving part-way through a tick leaves the rest of it for the action.
                used = distance(x0, y0, agent.x, agent.y) / self.config.world.movement_speed_per_tick
                time_fraction = max(0.0, time_fraction - used)
                if time_fraction < 0.25:
                    agent.time_allocation["travel"] = agent.time_allocation.get("travel", 0) + 1
                    return
                self.executed[agent.id] = task.action
        spec = REGISTRY.get(task.action)
        if spec is None:
            self._fail_task(agent, task, "unknown_action")
            return
        energy_need = spec.energy_cost(self.config) * time_fraction
        if energy_need > agent.energy + 1e-9:
            self._fail_task(agent, task, "insufficient_energy")
            return
        status = spec.tick(self, agent, task, time_fraction)
        agent.time_allocation[task.action] = agent.time_allocation.get(task.action, 0) + 1
        if status.startswith("failed"):
            self._fail_task(agent, task, status.split(":", 1)[1] if ":" in status else "failed")
            return
        task.remaining_ticks -= 1
        if status == "done" or task.remaining_ticks <= 0:
            self._finish_task(agent, task)

    def _travel(self, agent: Agent, task: Task) -> tuple[bool, bool]:
        """Returns (arrived, moved_this_tick)."""
        if task.travel_to.startswith("agent:"):
            other = self.world.agents.get(task.travel_to.split(":", 1)[1])
            if other is None or not other.alive:
                self._fail_task(agent, task, "target_unavailable")
                return False, False
            stop = self.config.world.interaction_radius * 0.8
            if distance(agent.x, agent.y, other.x, other.y) <= stop + ARRIVAL_TOLERANCE:
                return True, False
            return step_towards(self, agent, other.x, other.y, stop), True
        loc = self.world.locations.get(task.travel_to)
        if loc is None:
            self._fail_task(agent, task, "invalid_target")
            return False, False
        stop = loc.radius * 0.5
        if distance(agent.x, agent.y, loc.x, loc.y) <= stop + ARRIVAL_TOLERANCE:
            return True, False
        return step_towards(self, agent, loc.x, loc.y, stop), True

    def _finish_task(self, agent: Agent, task: Task) -> None:
        agent.current_task = None

    def _fail_task(self, agent: Agent, task: Task, reason: str) -> None:
        if agent.current_task is not task:
            return
        agent.current_task = None
        agent.last_failure = f"{task.action}: {reason}"
        self.adjust_emotion(agent, "frustration", 0.15)
        agent.bump_stat("failed_actions")
        self.observe(agent, "failure", f"I could not continue to {task.action} ({reason}).", importance=0.5)
        self.emit("action_failed", f"{agent.name} could not {task.action}: {reason}", agent=agent,
                  data={"action": task.action, "reason": reason}, importance=0.3)

    # ------------------------------------------------------------------
    # Needs, emotions, death
    # ------------------------------------------------------------------
    def _update_needs(self, agent: Agent) -> None:
        rc = self.config.resources
        health_before = agent.health
        agent.hunger = round(min(rc.maximum_hunger, agent.hunger + rc.hunger_increase_per_tick), 4)
        if self.executed.get(agent.id) != "rest":
            self.spend_energy(agent, rc.passive_energy_drain_per_tick)
        if agent.energy <= 0:
            self.damage(agent, rc.exhaustion_damage_per_tick, "exhaustion")
        if agent.hunger >= rc.critical_hunger:
            agent.critical_hunger_ticks += 1
            self.damage(agent, rc.starvation_damage_per_tick, "starvation")
        else:
            agent.critical_hunger_ticks = 0
        if (agent.health >= health_before and agent.hunger < rc.health_recovery_max_hunger
                and agent.energy > 20):
            agent.health = round(min(rc.maximum_health, agent.health + rc.natural_health_recovery_per_tick), 4)
        self._update_emotions(agent)
        ex_mod.decay_signals(self.config.existential_goal, agent)

    def _update_emotions(self, agent: Agent) -> None:
        sc = self.config.social
        e = agent.emotions
        pressure = self.need_pressure(agent)
        stress_target = min(1.0, 0.55 * pressure + 0.25 * (1 - e.get("safety", 0.7)) + 0.2 * e.get("overload", 0))
        e["stress"] = round(e.get("stress", 0) + (stress_target - e.get("stress", 0)) * 0.15, 4)
        done = self.executed.get(agent.id)
        if done not in ("socialize", "talk"):
            e["loneliness"] = round(min(1.0, e.get("loneliness", 0) + sc.loneliness_increase_per_tick * (
                0.5 + agent.personality.get("sociability", 0.5))), 4)
        happy_target = max(0.0, min(1.0, 0.65 - 0.4 * e["stress"] - 0.25 * e["loneliness"]
                                    - 0.15 * e.get("frustration", 0)))
        e["happiness"] = round(e.get("happiness", 0.5) + (happy_target - e.get("happiness", 0.5)) * 0.05, 4)
        e["frustration"] = round(e.get("frustration", 0) * 0.95, 4)
        if done not in ("explore", "study"):
            e["curiosity_activation"] = round(min(1.0, e.get("curiosity_activation", 0)
                                                  + 0.01 * agent.personality.get("curiosity", 0.5)), 4)
        e["safety"] = round(e.get("safety", 0.7) + (0.8 - e.get("safety", 0.7)) * 0.02
                            - (0.02 if agent.health < 30 else 0.0), 4)
        e["overload"] = round(e.get("overload", 0) * 0.8, 4)
        agent.current_mood = self._mood(agent)

    def _mood(self, agent: Agent) -> str:
        e = agent.emotions
        if agent.hunger >= self.config.resources.critical_hunger:
            return "starving"
        if agent.energy < 20:
            return "exhausted"
        if e.get("stress", 0) > 0.6:
            return "stressed"
        if e.get("frustration", 0) > 0.5:
            return "frustrated"
        if e.get("loneliness", 0) > 0.6:
            return "lonely"
        if agent.existential.active:
            return "contemplative"
        if e.get("happiness", 0) > 0.6:
            return "content"
        if e.get("curiosity_activation", 0) > 0.6:
            return "curious"
        return "calm"

    def _ambient_hazards(self) -> None:
        p = self.config.world.ambient_hazard_probability
        if p <= 0:
            return
        rng = self.streams["environment"]
        for agent in sorted(self.world.alive_agents(), key=lambda a: a.id):
            if rng.random() < p:
                self.damage(agent, self.config.world.hazard_damage, "hazard")
                self.adjust_emotion(agent, "safety", -0.3)
                self.emit("hazard", f"{agent.name} was hurt by an environmental hazard", agent=agent,
                          data={"damage": self.config.world.hazard_damage}, importance=0.7)

    def _check_death(self, agent: Agent) -> None:
        rc = self.config.resources
        cause = None
        if agent.health <= 0:
            cause = agent.last_damage_cause or "health_depleted"
        elif agent.critical_hunger_ticks > rc.max_critical_hunger_ticks:
            cause = "prolonged_starvation"
        if cause is None:
            return
        self._kill(agent, cause)

    def _kill(self, agent: Agent, cause: str) -> None:
        world = self.world
        agent.alive = False
        agent.current_task = None
        agent.current_action = "dead"
        agent.current_mood = "dead"
        info = {
            "tick": world.tick, "time": self.time_label(), "cause": cause,
            "last_actions": list(agent.recent_actions[-5:]),
            "state": {"tokens": agent.tokens, "food": agent.food, "hunger": agent.hunger,
                      "energy": agent.energy, "health": agent.health},
        }
        agent.death = info
        self._result.deaths.append({"agent_id": agent.id, "name": agent.name, **info})
        self.emit("death", f"{agent.name} died ({cause.replace('_', ' ')})", agent=agent, data=info, importance=1.0)
        for witness in self.agents_within(agent, self.config.world.perception_radius):
            self.remember(witness, f"I saw {agent.name} die ({cause.replace('_', ' ')}).", kind="event",
                          importance=0.9, related=[agent.id], tags=["death", "witness"])
            witness.existential.uncertainty = min(1.0, witness.existential.uncertainty + 0.6)
            witness.existential.novelty = min(1.0, witness.existential.novelty + 0.3)
            self.adjust_emotion(witness, "stress", 0.3)
            self.adjust_emotion(witness, "safety", -0.2)
        for offer in world.trade_offers.values():
            if offer.status == "pending" and agent.id in (offer.from_id, offer.to_id):
                offer.status = "expired"
        if self.config.simulation.enable_replacement:
            idx = world.counters.get("a", len(world.agents))
            new = create_agent(self.config, self.streams, idx, tick=world.tick, controller=agent.controller)
            world.counters["a"] = idx + 1
            world.agents[new.id] = new
            self.emit("birth", f"{new.name} arrived to replace {agent.name}", agent=new, importance=0.6)

    # ------------------------------------------------------------------
    # Perception
    # ------------------------------------------------------------------
    def _detect_meetings(self) -> None:
        radius = self.config.world.perception_radius
        alive = sorted(self.world.alive_agents(), key=lambda a: a.id)
        for i, a in enumerate(alive):
            for b in alive[i + 1:]:
                if b.id in a.relationships and a.id in b.relationships:
                    continue
                if distance(a.x, a.y, b.x, b.y) > radius:
                    continue
                for x, y in ((a, b), (b, a)):
                    if y.id not in x.relationships:
                        self.relationship(x, y)
                        self.observe(x, "meeting", f"I noticed {y.name} nearby for the first time.",
                                     related=[y.id], importance=0.4)
                        self.remember(x, f"I met {y.name}.", kind="event", importance=0.3, related=[y.id],
                                      tags=["meeting"])
                        x.existential.novelty = min(1.0, x.existential.novelty + 0.1)

    def _propagate_observations(self) -> None:
        radius = self.config.world.perception_radius
        alive = [a for a in self.world.agents.values() if a.alive]
        for event in self._result.events:
            if event.visibility == "public" and event.x is not None and event.importance >= 0.2:
                for obs in alive:
                    if obs.id == event.agent_id or obs.id == event.target_id and event.type == "give":
                        continue
                    if distance(obs.x, obs.y, event.x, event.y) <= radius:
                        self.observe(obs, event.type, event.summary,
                                     related=[i for i in (event.agent_id, event.target_id) if i], importance=event.importance)
                        if event.type == "reflect" and event.data.get("existential"):
                            obs.existential.discussion_exposure = min(1.0, obs.existential.discussion_exposure + 0.1)
            elif event.visibility == "private":
                for pid in event.participants:
                    if pid == event.agent_id or event.type == "message":
                        continue
                    obs = self.world.agents.get(pid)
                    if obs is not None and obs.alive:
                        self.observe(obs, event.type, event.summary,
                                     related=[i for i in (event.agent_id, event.target_id) if i],
                                     importance=event.importance)

    # ------------------------------------------------------------------
    # Daily rules
    # ------------------------------------------------------------------
    def _end_of_day(self) -> None:
        world = self.world
        day = self.day + 1
        for loc in world.locations.values():
            if loc.type == "food" and loc.max_stock is not None:
                loc.stock = min(loc.max_stock, (loc.stock or 0) + (loc.restock_per_day or 0))
        upkeep = self.config.resources.daily_upkeep
        for agent in sorted(world.alive_agents(), key=lambda a: a.id):
            if upkeep > 0:
                paid = min(agent.tokens, upkeep)
                agent.tokens = round(agent.tokens - paid, 4)
                if paid < upkeep:
                    self.adjust_emotion(agent, "stress", 0.1)
                    self.damage(agent, (upkeep - paid) * 2, "unpaid_upkeep")
            self._daily_summary(agent, day)
            agent.work_ticks_today = 0
            for rel in agent.relationships.values():
                trust_mod.decay_towards_prior(self.config.trust, rel)
            agent.day_stats_start = {**{f"ta_{k}": v for k, v in agent.time_allocation.items()},
                                     **{f"st_{k}": v for k, v in agent.stats.items()}}

    def _daily_summary(self, agent: Agent, day: int) -> None:
        start = agent.day_stats_start
        alloc = {k: v - start.get(f"ta_{k}", 0) for k, v in agent.time_allocation.items()}
        alloc = {k: v for k, v in alloc.items() if v > 0}
        top = sorted(alloc.items(), key=lambda kv: -kv[1])[:4]
        tpd = self.config.simulation.ticks_per_day
        hours = 24 / tpd
        parts = ", ".join(f"{k} {v * hours:g}h" for k, v in top) or "nothing notable"
        talked = sorted({
            self.world.agents[r].name for m in agent.memories if m.tick >= (day - 1) * tpd
            for r in m.related_agents if r in self.world.agents
        })
        line = f"Day {day}: {parts}; ended with {agent.tokens:.0f} tokens, mood {agent.current_mood}"
        if talked:
            line += f"; dealt with {', '.join(talked[:4])}"
        agent.life_summary.append(line + ".")
        del agent.life_summary[:-30]

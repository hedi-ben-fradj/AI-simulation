"""Repository: all reads and writes of persistent simulation data.

Methods are synchronous; async callers run them in a worker thread. A whole
tick is written in one transaction so a crash never leaves a half-written tick.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from ..engine.simulation import Simulation, TickResult
from .db import Database
from .models import (
    AgentRow,
    DaySummaryRow,
    DecisionRow,
    EventRow,
    ExperimentRow,
    LLMUsageRow,
    MemoryRow,
    MessageRow,
    MetricRow,
    RelationshipRow,
    TraitHistoryRow,
    TrustChangeRow,
    WorldRow,
)

PER_TICK_TABLES = (EventRow, MessageRow, DecisionRow, MemoryRow, TrustChangeRow, TraitHistoryRow, LLMUsageRow)


def agent_state_summary(agent) -> dict[str, Any]:
    return {
        "x": agent.x, "y": agent.y, "tokens": agent.tokens, "food": agent.food, "energy": agent.energy,
        "health": agent.health, "hunger": agent.hunger, "knowledge": agent.knowledge, "artworks": agent.artworks,
        "mood": agent.current_mood, "action": agent.current_action, "emotions": agent.emotions,
        "time_allocation": agent.time_allocation, "stats": agent.stats,
        "existential": {
            "activations": agent.existential.activations, "opportunities": agent.existential.opportunities,
            "ticks_contemplating": agent.existential.ticks_contemplating,
            "conversations": agent.existential.conversations, "beliefs": len(agent.existential.beliefs),
        },
    }


class Repository:
    def __init__(self, db: Database):
        self.db = db
        # SQLite allows one writer at a time; serialise writes from worker threads.
        self._write_lock = threading.Lock() if db.is_sqlite else None

    def _locked(self):
        return self._write_lock if self._write_lock is not None else _NullLock()

    # ------------------------------------------------------------------ worlds
    def create_world(self, sim: Simulation, preset: str | None, experiment_id: str | None = None,
                     condition: str | None = None) -> None:
        with self._locked(), self.db.session() as s:
            s.add(WorldRow(
                id=sim.world.id, name=sim.world.name, preset=preset, config=sim.config.model_dump(mode="json"),
                seed=sim.config.simulation.random_seed, status="paused", tick=sim.world.tick,
                snapshot_tick=sim.world.tick, snapshot=sim.snapshot(), experiment_id=experiment_id,
                condition=condition,
            ))
            s.flush()
            self._write_agents(s, sim)

    def save_tick(self, sim: Simulation, result: TickResult, status: str | None = None,
                  llm_usage: list[dict[str, Any]] | None = None, llm_spend_usd: float | None = None,
                  force_snapshot: bool = False) -> None:
        wid = sim.world.id
        interval = sim.config.simulation.snapshot_interval_ticks
        take_snapshot = force_snapshot or sim.world.tick % interval == 0
        with self._locked(), self.db.session() as s:
            # Bulk Core inserts (executemany) are far cheaper than ORM unit-of-work for per-tick rows.
            _bulk(s, EventRow, [{"world_id": wid, **e.model_dump()} for e in result.events])
            _bulk(s, MessageRow, [{
                "world_id": wid, "message_id": m.id, "sender_id": m.sender_id, "recipient_id": m.recipient_id,
                "content": m.content, "tokens": m.tokens, "sent_tick": m.sent_tick, "deliver_tick": m.deliver_tick,
                "token_cost": m.token_cost, "existential": m.existential} for m in result.messages])
            for message_id, read_tick in result.reads:
                s.execute(update(MessageRow).where(MessageRow.world_id == wid, MessageRow.message_id == message_id)
                          .values(read_tick=read_tick))
            _bulk(s, DecisionRow, [{
                "world_id": wid, "tick": d.tick, "agent_id": d.agent_id, "source": d.source, "valid": d.valid,
                "reason": d.reason, "applied_action": d.applied_action, "visible_intention": d.visible_intention,
                "existential_active": d.existential_active, "fallback_reason": d.fallback_reason,
                "latency_ms": d.latency_ms, "proposal": d.proposal, "notes": d.notes} for d in result.decisions])
            _bulk(s, MemoryRow, [{
                "world_id": wid, "agent_id": aid, "memory_id": m.id, "tick": m.tick, "kind": m.kind,
                "content": m.content, "importance": m.importance, "related_agents": m.related_agents,
                "tags": m.tags, "source": m.source} for aid, m in result.memories])
            _bulk(s, TrustChangeRow, [{"world_id": wid, **t} for t in result.trust_changes])
            _bulk(s, TraitHistoryRow, [{"world_id": wid, **t} for t in result.trait_changes])
            _bulk(s, MetricRow, [{"world_id": wid, "tick": result.tick, "data": result.metrics}])
            _bulk(s, LLMUsageRow, [{"world_id": wid, **u} for u in llm_usage or []])
            world = s.get(WorldRow, wid)
            if world is None:
                raise KeyError(wid)
            world.tick = sim.world.tick
            if status is not None:
                world.status = status
            if llm_spend_usd is not None:
                world.llm_spend_usd = llm_spend_usd
            if take_snapshot:
                world.snapshot = sim.snapshot()
                world.snapshot_tick = sim.world.tick
            # The agents/relationships tables are a queryable mirror (live views read memory);
            # refreshing them is O(n^2) in relationships, so do it at most once per simulated day.
            if force_snapshot or sim.world.tick % sim.config.simulation.ticks_per_day == 0:
                self._write_agents(s, sim)
            world.updated_at = datetime.now(timezone.utc)

    def _write_agents(self, s, sim: Simulation) -> None:
        wid = sim.world.id
        s.execute(delete(AgentRow).where(AgentRow.world_id == wid))
        s.execute(delete(RelationshipRow).where(RelationshipRow.world_id == wid))
        _bulk(s, AgentRow, [{
            "world_id": wid, "agent_id": a.id, "name": a.name, "controller": a.controller, "alive": a.alive,
            "born_tick": a.born_tick, "death_tick": (a.death or {}).get("tick"),
            "death_cause": (a.death or {}).get("cause"), "personality": a.personality,
            "state": agent_state_summary(a), "updated_tick": sim.world.tick} for a in sim.world.agents.values()])
        _bulk(s, RelationshipRow, [{
            "world_id": wid, "agent_id": a.id, "other_id": r.other_id, "trust_alpha": r.trust_alpha,
            "trust_beta": r.trust_beta, "trust": r.trust, "familiarity": r.familiarity, "affinity": r.affinity,
            "interactions": r.interactions, "updated_tick": sim.world.tick}
            for a in sim.world.agents.values() for r in a.relationships.values()])

    def set_status(self, world_id: str, status: str) -> None:
        with self._locked(), self.db.session() as s:
            world = s.get(WorldRow, world_id)
            if world is not None:
                world.status = status

    def get_world(self, world_id: str) -> WorldRow | None:
        with self.db.session() as s:
            return s.get(WorldRow, world_id)

    def list_worlds(self, include_experiments: bool = False) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(WorldRow.id, WorldRow.name, WorldRow.preset, WorldRow.status, WorldRow.tick, WorldRow.seed,
                       WorldRow.experiment_id, WorldRow.condition, WorldRow.llm_spend_usd, WorldRow.created_at,
                       WorldRow.updated_at).order_by(WorldRow.created_at.desc())
            if not include_experiments:
                q = q.where(WorldRow.experiment_id.is_(None))
            return [dict(r._mapping) for r in s.execute(q)]

    def delete_world(self, world_id: str) -> None:
        with self._locked(), self.db.session() as s:
            for table in (*PER_TICK_TABLES, MetricRow, RelationshipRow, AgentRow, DaySummaryRow):
                s.execute(delete(table).where(table.world_id == world_id))
            s.execute(delete(WorldRow).where(WorldRow.id == world_id))

    def truncate_after(self, world_id: str, tick: int) -> None:
        """Drop per-tick records at or after ``tick`` (used when restoring from an older snapshot)."""
        with self._locked(), self.db.session() as s:
            for table, col in ((EventRow, EventRow.tick), (MessageRow, MessageRow.sent_tick),
                               (DecisionRow, DecisionRow.tick), (MemoryRow, MemoryRow.tick),
                               (TrustChangeRow, TrustChangeRow.tick), (TraitHistoryRow, TraitHistoryRow.tick),
                               (MetricRow, MetricRow.tick), (LLMUsageRow, LLMUsageRow.tick)):
                s.execute(delete(table).where(table.world_id == world_id, col >= tick))
            # Days that are no longer complete are written again when they finish.
            s.execute(delete(DaySummaryRow).where(DaySummaryRow.world_id == world_id, DaySummaryRow.to_tick > tick))
            # Reads that happened after the snapshot are replayed too.
            s.execute(update(MessageRow).where(MessageRow.world_id == world_id, MessageRow.read_tick >= tick)
                      .values(read_tick=None))
            world = s.get(WorldRow, world_id)
            if world is not None:
                world.tick = tick

    # ------------------------------------------------------------------ queries
    def events(self, world_id: str, since_tick: int | None = None, until_tick: int | None = None,
               agent_id: str | None = None, types: list[str] | None = None, include_system: bool = True,
               limit: int = 200) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(EventRow).where(EventRow.world_id == world_id)
            if since_tick is not None:
                q = q.where(EventRow.tick >= since_tick)
            if until_tick is not None:
                q = q.where(EventRow.tick <= until_tick)
            if agent_id:
                q = q.where((EventRow.agent_id == agent_id) | (EventRow.target_id == agent_id))
            if types:
                q = q.where(EventRow.type.in_(types))
            if not include_system:
                q = q.where(EventRow.visibility != "system")
            q = q.order_by(EventRow.id.desc()).limit(limit)
            rows = list(s.scalars(q))
        return [_event_dict(r) for r in reversed(rows)]

    def messages(self, world_id: str, agent_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(MessageRow).where(MessageRow.world_id == world_id)
            if agent_id:
                q = q.where((MessageRow.sender_id == agent_id) | (MessageRow.recipient_id == agent_id))
            rows = list(s.scalars(q.order_by(MessageRow.id.desc()).limit(limit)))
        return [{
            "id": r.message_id, "sender_id": r.sender_id, "recipient_id": r.recipient_id, "content": r.content,
            "tokens": r.tokens, "sent_tick": r.sent_tick, "deliver_tick": r.deliver_tick,
            "token_cost": r.token_cost, "existential": r.existential, "read_tick": r.read_tick} for r in reversed(rows)]

    def messages_among(self, world_id: str, agent_ids: list[str], limit: int = 500) -> list[dict[str, Any]]:
        """Messages whose sender and recipient are both in ``agent_ids`` (oldest first)."""
        with self.db.session() as s:
            q = (select(MessageRow).where(MessageRow.world_id == world_id, MessageRow.sender_id.in_(agent_ids),
                                          MessageRow.recipient_id.in_(agent_ids))
                 .order_by(MessageRow.id.desc()).limit(limit))
            rows = list(s.scalars(q))
        return [{
            "id": r.message_id, "sender_id": r.sender_id, "recipient_id": r.recipient_id, "content": r.content,
            "tokens": r.tokens, "sent_tick": r.sent_tick, "deliver_tick": r.deliver_tick,
            "token_cost": r.token_cost, "existential": r.existential, "read_tick": r.read_tick} for r in reversed(rows)]

    def day_records(self, world_id: str, from_tick: int, to_tick: int) -> dict[str, list[dict[str, Any]]]:
        """Everything recorded in ticks ``from_tick`` .. ``to_tick - 1`` (for the chronicle)."""
        w = world_id
        with self.db.session() as s:
            events = list(s.scalars(select(EventRow).where(
                EventRow.world_id == w, EventRow.tick >= from_tick, EventRow.tick < to_tick,
                EventRow.type.notin_(("work", "eat", "arrive", "buy_food", "study", "trait_change")))
                .order_by(EventRow.id)))
            messages = list(s.scalars(select(MessageRow).where(
                MessageRow.world_id == w, MessageRow.sent_tick >= from_tick, MessageRow.sent_tick < to_tick)
                .order_by(MessageRow.id)))
            decisions = s.execute(select(
                DecisionRow.tick, DecisionRow.agent_id, DecisionRow.source, DecisionRow.valid, DecisionRow.reason,
                DecisionRow.applied_action, DecisionRow.visible_intention, DecisionRow.existential_active)
                .where(DecisionRow.world_id == w, DecisionRow.tick >= from_tick, DecisionRow.tick < to_tick)
                .order_by(DecisionRow.id)).all()
            memories = list(s.scalars(select(MemoryRow).where(
                MemoryRow.world_id == w, MemoryRow.tick >= from_tick, MemoryRow.tick < to_tick,
                MemoryRow.kind.in_(("reflection", "belief", "note"))).order_by(MemoryRow.id)))
            trust = list(s.scalars(select(TrustChangeRow).where(
                TrustChangeRow.world_id == w, TrustChangeRow.tick >= from_tick, TrustChangeRow.tick < to_tick)
                .order_by(TrustChangeRow.id)))
            traits = list(s.scalars(select(TraitHistoryRow).where(
                TraitHistoryRow.world_id == w, TraitHistoryRow.tick >= from_tick, TraitHistoryRow.tick < to_tick)
                .order_by(TraitHistoryRow.id)))
            metrics = [r.data for r in s.execute(select(MetricRow.data).where(
                MetricRow.world_id == w, MetricRow.tick >= from_tick, MetricRow.tick < to_tick)
                .order_by(MetricRow.tick))]
        return {
            "events": [_event_dict(r) for r in events],
            "messages": [{"id": r.message_id, "sender_id": r.sender_id, "recipient_id": r.recipient_id,
                          "content": r.content, "sent_tick": r.sent_tick, "deliver_tick": r.deliver_tick,
                          "existential": r.existential, "read_tick": r.read_tick} for r in messages],
            "decisions": [{"tick": d.tick, "agent_id": d.agent_id, "source": d.source, "valid": d.valid,
                           "reason": d.reason, "applied_action": d.applied_action,
                           "visible_intention": d.visible_intention, "existential_active": d.existential_active}
                          for d in decisions],
            "memories": [{"agent_id": r.agent_id, "tick": r.tick, "kind": r.kind, "content": r.content,
                          "tags": r.tags, "source": r.source} for r in memories],
            "trust_changes": [{"tick": r.tick, "agent_id": r.agent_id, "other_id": r.other_id, "reason": r.reason,
                               "trust_before": r.trust_before, "trust_after": r.trust_after} for r in trust],
            "trait_changes": [{"tick": r.tick, "agent_id": r.agent_id, "trait": r.trait, "old": r.old, "new": r.new}
                              for r in traits],
            "metrics": metrics,
        }

    # ------------------------------------------------------------------ chronicle
    def save_day_summary(self, world_id: str, day: int, from_tick: int, to_tick: int, headline: str, story: str,
                         digest: dict[str, Any], narrator: str = "template", model: str | None = None,
                         notable: list[str] | None = None, only_if_missing: bool = False) -> bool:
        """Insert or replace a day's storyline; with ``only_if_missing`` never replace one. Returns True if saved."""
        try:
            return self._save_day_summary(world_id, day, from_tick, to_tick, headline, story, digest, narrator, model,
                                          notable, only_if_missing)
        except IntegrityError:  # another writer inserted the same day concurrently
            if only_if_missing:
                return False
            return self._save_day_summary(world_id, day, from_tick, to_tick, headline, story, digest, narrator, model,
                                          notable, False)

    def _save_day_summary(self, world_id, day, from_tick, to_tick, headline, story, digest, narrator, model,
                          notable, only_if_missing) -> bool:
        with self._locked(), self.db.session() as s:
            row = s.scalars(select(DaySummaryRow).where(DaySummaryRow.world_id == world_id,
                                                        DaySummaryRow.day == day)).first()
            if row is not None and only_if_missing:
                return False
            if row is None:
                row = DaySummaryRow(world_id=world_id, day=day)
                s.add(row)
            row.from_tick, row.to_tick, row.headline, row.story = from_tick, to_tick, headline, story
            row.digest, row.narrator, row.model, row.notable = digest, narrator, model, notable or []
            row.updated_at = datetime.now(timezone.utc)
        return True

    def day_summaries(self, world_id: str, with_digest: bool = False) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = list(s.scalars(select(DaySummaryRow).where(DaySummaryRow.world_id == world_id)
                                  .order_by(DaySummaryRow.day)))
        return [_day_dict(r, with_digest) for r in rows]

    def day_summary(self, world_id: str, day: int) -> dict[str, Any] | None:
        with self.db.session() as s:
            row = s.scalars(select(DaySummaryRow).where(DaySummaryRow.world_id == world_id,
                                                        DaySummaryRow.day == day)).first()
            return _day_dict(row, True) if row else None

    def intentions(self, world_id: str, agent_ticks: set[tuple[str, int]]) -> dict[tuple[str, int], str]:
        """Visible intention of each (agent, tick) decision, where one was recorded."""
        if not agent_ticks:
            return {}
        agents = {a for a, _ in agent_ticks}
        ticks = {t for _, t in agent_ticks}
        with self.db.session() as s:
            rows = s.execute(select(DecisionRow.agent_id, DecisionRow.tick, DecisionRow.visible_intention)
                             .where(DecisionRow.world_id == world_id, DecisionRow.agent_id.in_(agents),
                                    DecisionRow.tick.in_(ticks))).all()
        return {(a, t): text for a, t, text in rows if (a, t) in agent_ticks and text}

    def events_among(self, world_id: str, agent_ids: list[str], types: list[str],
                     limit: int = 300) -> list[dict[str, Any]]:
        """Events of the given types where both the actor and the target are in ``agent_ids``."""
        with self.db.session() as s:
            q = (select(EventRow).where(EventRow.world_id == world_id, EventRow.type.in_(types),
                                        EventRow.agent_id.in_(agent_ids), EventRow.target_id.in_(agent_ids))
                 .order_by(EventRow.id.desc()).limit(limit))
            rows = list(s.scalars(q))
        return [_event_dict(r) for r in reversed(rows)]

    def decisions(self, world_id: str, agent_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(DecisionRow).where(DecisionRow.world_id == world_id)
            if agent_id:
                q = q.where(DecisionRow.agent_id == agent_id)
            rows = list(s.scalars(q.order_by(DecisionRow.id.desc()).limit(limit)))
        return [{
            "tick": r.tick, "agent_id": r.agent_id, "source": r.source, "valid": r.valid, "reason": r.reason,
            "applied_action": r.applied_action, "visible_intention": r.visible_intention,
            "existential_active": r.existential_active, "fallback_reason": r.fallback_reason,
            "latency_ms": r.latency_ms, "proposal": r.proposal, "notes": r.notes} for r in reversed(rows)]

    def memories(self, world_id: str, agent_id: str, limit: int = 200, kind: str | None = None) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(MemoryRow).where(MemoryRow.world_id == world_id, MemoryRow.agent_id == agent_id)
            if kind:
                q = q.where(MemoryRow.kind == kind)
            rows = list(s.scalars(q.order_by(MemoryRow.id.desc()).limit(limit)))
        return [{
            "id": r.memory_id, "tick": r.tick, "kind": r.kind, "content": r.content, "importance": r.importance,
            "related_agents": r.related_agents, "tags": r.tags, "source": r.source} for r in reversed(rows)]

    def trait_history(self, world_id: str, agent_id: str | None = None) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(TraitHistoryRow).where(TraitHistoryRow.world_id == world_id)
            if agent_id:
                q = q.where(TraitHistoryRow.agent_id == agent_id)
            rows = list(s.scalars(q.order_by(TraitHistoryRow.id)))
        return [{"tick": r.tick, "agent_id": r.agent_id, "trait": r.trait, "old": r.old, "new": r.new,
                 "target": r.target, "evidence_weight": r.evidence_weight} for r in rows]

    def trust_changes(self, world_id: str, agent_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(TrustChangeRow).where(TrustChangeRow.world_id == world_id)
            if agent_id:
                q = q.where((TrustChangeRow.agent_id == agent_id) | (TrustChangeRow.other_id == agent_id))
            rows = list(s.scalars(q.order_by(TrustChangeRow.id.desc()).limit(limit)))
        return [{"tick": r.tick, "agent_id": r.agent_id, "other_id": r.other_id, "reason": r.reason,
                 "positive": r.positive, "weight": r.weight, "trust_before": r.trust_before,
                 "trust_after": r.trust_after} for r in reversed(rows)]

    def metrics(self, world_id: str, since_tick: int = 0, every: int = 1, limit: int = 5000) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = (select(MetricRow.tick, MetricRow.data)
                 .where(MetricRow.world_id == world_id, MetricRow.tick >= since_tick)
                 .order_by(MetricRow.tick))
            rows = [r.data for r in s.execute(q) if every <= 1 or r.tick % every == 0]
        return rows[-limit:]

    def relationships(self, world_id: str) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = list(s.scalars(select(RelationshipRow).where(RelationshipRow.world_id == world_id)))
        return [{"agent_id": r.agent_id, "other_id": r.other_id, "trust": r.trust, "familiarity": r.familiarity,
                 "affinity": r.affinity, "interactions": r.interactions} for r in rows]

    def agents(self, world_id: str) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = list(s.scalars(select(AgentRow).where(AgentRow.world_id == world_id).order_by(AgentRow.agent_id)))
        return [{"id": r.agent_id, "name": r.name, "controller": r.controller, "alive": r.alive,
                 "born_tick": r.born_tick, "death_tick": r.death_tick, "death_cause": r.death_cause,
                 "personality": r.personality, "state": r.state} for r in rows]

    # ---------------------------------------------------------------- LLM usage
    def llm_usage_summary(self, world_id: str) -> dict[str, Any]:
        with self.db.session() as s:
            row = s.execute(
                select(func.count(LLMUsageRow.id), func.coalesce(func.sum(LLMUsageRow.input_tokens), 0),
                       func.coalesce(func.sum(LLMUsageRow.output_tokens), 0),
                       func.coalesce(func.sum(LLMUsageRow.cost_usd), 0.0),
                       func.coalesce(func.avg(LLMUsageRow.latency_ms), 0.0))
                .where(LLMUsageRow.world_id == world_id)).one()
            failures = s.scalar(select(func.count(LLMUsageRow.id)).where(
                LLMUsageRow.world_id == world_id, LLMUsageRow.success.is_(False)))
            by_agent = s.execute(
                select(LLMUsageRow.agent_id, func.count(LLMUsageRow.id), func.sum(LLMUsageRow.cost_usd))
                .where(LLMUsageRow.world_id == world_id).group_by(LLMUsageRow.agent_id)).all()
            errors = s.execute(
                select(LLMUsageRow.error, func.count(LLMUsageRow.id))
                .where(LLMUsageRow.world_id == world_id, LLMUsageRow.success.is_(False))
                .group_by(LLMUsageRow.error)).all()
        return {
            "requests": row[0], "input_tokens": int(row[1]), "output_tokens": int(row[2]),
            "cost_usd": round(float(row[3]), 6), "mean_latency_ms": round(float(row[4]), 1),
            "failures": failures or 0,
            "by_agent": {aid or "-": {"requests": n, "cost_usd": round(float(c or 0), 6)} for aid, n, c in by_agent},
            "errors": {(e or "unknown")[:80]: n for e, n in errors},
        }

    def llm_usage(self, world_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = list(s.scalars(select(LLMUsageRow).where(LLMUsageRow.world_id == world_id)
                                  .order_by(LLMUsageRow.id.desc()).limit(limit)))
        return [{"tick": r.tick, "agent_id": r.agent_id, "provider": r.provider, "model": r.model,
                 "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "cost_usd": r.cost_usd,
                 "latency_ms": r.latency_ms, "success": r.success, "error": r.error, "attempts": r.attempts}
                for r in reversed(rows)]

    # -------------------------------------------------------------- experiments
    def create_experiment(self, exp_id: str, name: str, description: str, spec: dict[str, Any]) -> None:
        with self._locked(), self.db.session() as s:
            s.add(ExperimentRow(id=exp_id, name=name, description=description, spec=spec, status="pending"))

    def update_experiment(self, exp_id: str, **fields: Any) -> None:
        with self._locked(), self.db.session() as s:
            row = s.get(ExperimentRow, exp_id)
            if row is None:
                return
            for k, v in fields.items():
                setattr(row, k, v)
            if fields.get("status") in ("completed", "failed", "cancelled"):
                row.finished_at = datetime.now(timezone.utc)

    def get_experiment(self, exp_id: str) -> dict[str, Any] | None:
        with self.db.session() as s:
            row = s.get(ExperimentRow, exp_id)
            return _experiment_dict(row) if row else None

    def list_experiments(self) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = list(s.scalars(select(ExperimentRow).order_by(ExperimentRow.created_at.desc())))
        return [{k: v for k, v in _experiment_dict(r).items() if k != "results"} for r in rows]

    def experiment_worlds(self, exp_id: str) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = s.execute(select(WorldRow.id, WorldRow.condition, WorldRow.seed, WorldRow.tick, WorldRow.status,
                                    WorldRow.llm_spend_usd).where(WorldRow.experiment_id == exp_id)).all()
        return [dict(r._mapping) for r in rows]

    def delete_experiment(self, exp_id: str) -> None:
        for w in self.experiment_worlds(exp_id):
            self.delete_world(w["id"])
        with self._locked(), self.db.session() as s:
            s.execute(delete(ExperimentRow).where(ExperimentRow.id == exp_id))


def _bulk(session, table, rows: list[dict[str, Any]]) -> None:
    if rows:
        session.execute(insert(table), rows)


def _day_dict(r: DaySummaryRow, with_digest: bool) -> dict[str, Any]:
    digest = r.digest or {}
    out = {"day": r.day, "from_tick": r.from_tick, "to_tick": r.to_tick, "headline": r.headline, "story": r.story,
           "notable": r.notable or [], "narrator": r.narrator, "model": r.model,
           "stats": digest.get("stats", {}), "economy": digest.get("economy", {}),
           "highlights": (digest.get("highlights") or [])[:8],
           "updated_at": r.updated_at.isoformat() if r.updated_at else None}
    if with_digest:
        out["digest"] = digest
    return out


def _event_dict(r: EventRow) -> dict[str, Any]:
    return {"id": r.id, "tick": r.tick, "type": r.type, "summary": r.summary, "agent_id": r.agent_id,
            "target_id": r.target_id, "visibility": r.visibility, "participants": r.participants, "data": r.data,
            "importance": r.importance, "x": r.x, "y": r.y}


def _experiment_dict(r: ExperimentRow) -> dict[str, Any]:
    return {"id": r.id, "name": r.name, "description": r.description, "spec": r.spec, "status": r.status,
            "progress": r.progress, "results": r.results, "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

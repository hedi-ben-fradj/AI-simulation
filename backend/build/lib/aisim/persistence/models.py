"""ORM models. Schema changes must go through Alembic migrations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class WorldRow(Base):
    __tablename__ = "worlds"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    preset: Mapped[str | None] = mapped_column(String(100))
    config: Mapped[dict[str, Any]] = mapped_column(JSONType)
    seed: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="paused")
    tick: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_tick: Mapped[int] = mapped_column(Integer, default=0)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    condition: Mapped[str | None] = mapped_column(String(100), nullable=True)
    llm_spend_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentRow(Base):
    __tablename__ = "agents"

    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    controller: Mapped[str] = mapped_column(String(20))
    alive: Mapped[bool] = mapped_column(Boolean, default=True)
    born_tick: Mapped[int] = mapped_column(Integer, default=0)
    death_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)
    death_cause: Mapped[str | None] = mapped_column(String(50), nullable=True)
    personality: Mapped[dict[str, Any]] = mapped_column(JSONType)
    state: Mapped[dict[str, Any]] = mapped_column(JSONType)
    updated_tick: Mapped[int] = mapped_column(Integer, default=0)


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_world_tick", "world_id", "tick"),
        Index("ix_events_world_agent", "world_id", "agent_id"),
        Index("ix_events_world_type", "world_id", "type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    tick: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    agent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    visibility: Mapped[str] = mapped_column(String(10))
    participants: Mapped[list[str]] = mapped_column(JSONType, default=list)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    importance: Mapped[float] = mapped_column(Float, default=0.3)
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)


class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_world_tick", "world_id", "sent_tick"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    message_id: Mapped[str] = mapped_column(String(32))
    sender_id: Mapped[str] = mapped_column(String(32), index=True)
    recipient_id: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer)
    sent_tick: Mapped[int] = mapped_column(Integer)
    deliver_tick: Mapped[int] = mapped_column(Integer)
    token_cost: Mapped[float] = mapped_column(Float)
    existential: Mapped[bool] = mapped_column(Boolean, default=False)


class DecisionRow(Base):
    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_world_agent_tick", "world_id", "agent_id", "tick"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    tick: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(20))
    valid: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    applied_action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    visible_intention: Mapped[str | None] = mapped_column(Text, nullable=True)
    existential_active: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    notes: Mapped[list[str]] = mapped_column(JSONType, default=list)


class MemoryRow(Base):
    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_world_agent", "world_id", "agent_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    agent_id: Mapped[str] = mapped_column(String(32))
    memory_id: Mapped[str] = mapped_column(String(32))
    tick: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float)
    related_agents: Mapped[list[str]] = mapped_column(JSONType, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    source: Mapped[str] = mapped_column(String(10))


class RelationshipRow(Base):
    __tablename__ = "relationships"

    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    other_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trust_alpha: Mapped[float] = mapped_column(Float)
    trust_beta: Mapped[float] = mapped_column(Float)
    trust: Mapped[float] = mapped_column(Float)
    familiarity: Mapped[int] = mapped_column(Integer)
    affinity: Mapped[float] = mapped_column(Float)
    interactions: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_tick: Mapped[int] = mapped_column(Integer)


class TrustChangeRow(Base):
    __tablename__ = "trust_changes"
    __table_args__ = (Index("ix_trust_changes_world_tick", "world_id", "tick"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    tick: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[str] = mapped_column(String(32))
    other_id: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(40))
    positive: Mapped[bool] = mapped_column(Boolean)
    weight: Mapped[float] = mapped_column(Float)
    trust_before: Mapped[float] = mapped_column(Float)
    trust_after: Mapped[float] = mapped_column(Float)


class TraitHistoryRow(Base):
    __tablename__ = "trait_history"
    __table_args__ = (Index("ix_trait_history_world_agent", "world_id", "agent_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    tick: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[str] = mapped_column(String(32))
    trait: Mapped[str] = mapped_column(String(40))
    old: Mapped[float] = mapped_column(Float)
    new: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    evidence_weight: Mapped[float] = mapped_column(Float)


class MetricRow(Base):
    __tablename__ = "metrics"

    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), primary_key=True)
    tick: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType)


class LLMUsageRow(Base):
    __tablename__ = "llm_usage"
    __table_args__ = (Index("ix_llm_usage_world_tick", "world_id", "tick"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    agent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tick: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentRow(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    spec: Mapped[dict[str, Any]] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

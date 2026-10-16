"""Authoritative world state.

State is held in Pydantic models so a whole world can be snapshotted to JSON
and restored exactly (including random generator state). Only the simulation
engine mutates these objects; LLMs only ever see derived, filtered views.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

TRAITS: tuple[str, ...] = (
    "artistic",
    "scientific_curiosity",
    "humor",
    "agreeableness",
    "sociability",
    "spirituality",
    "ambition",
    "empathy",
    "risk_tolerance",
    "honesty",
    "criminal_tendency",
    "persistence",
    "impulsivity",
    "curiosity",
    "generosity",
    "competitiveness",
)

TRAIT_DESCRIPTIONS: dict[str, str] = {
    "artistic": "tendency toward creative expression",
    "scientific_curiosity": "tendency to investigate and test hypotheses",
    "humor": "tendency to use humor",
    "agreeableness": "tendency toward cooperation and compromise",
    "sociability": "desire for social contact",
    "spirituality": "tendency to contemplate transcendent or existential questions",
    "ambition": "desire for achievement and progress",
    "empathy": "tendency to consider others' needs",
    "risk_tolerance": "willingness to accept uncertainty and danger",
    "honesty": "tendency to communicate truthfully",
    "criminal_tendency": "propensity to consider prohibited or harmful strategies",
    "persistence": "willingness to continue difficult tasks",
    "impulsivity": "tendency toward immediate action",
    "curiosity": "general tendency to explore unfamiliar things",
    "generosity": "tendency to share resources",
    "competitiveness": "desire to outperform others",
}

EMOTIONS: tuple[str, ...] = (
    "stress",
    "happiness",
    "frustration",
    "loneliness",
    "overload",
    "curiosity_activation",
    "safety",
)


class Location(BaseModel):
    id: str
    name: str
    type: str  # workplace | food | rest | gathering | wild
    x: float
    y: float
    radius: float = 6.0
    capacity: int | None = None
    stock: int | None = None
    max_stock: int | None = None
    restock_per_day: int | None = None
    price: float | None = None
    wage_multiplier: float = 1.0
    quality: float = 1.0
    # Agents using this location during the current tick (capacity accounting).
    occupancy: int = 0


class Task(BaseModel):
    """A committed action that may span several ticks."""

    action: str
    target: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    total_ticks: int = 1
    remaining_ticks: int = 1
    started_tick: int = 0
    intention: str | None = None
    source: str = "rule"  # rule | llm | fallback
    # Destination when the task begins with travel.
    travel_to: str | None = None
    # Steps queued after this one (e.g. move -> work).
    then: list[dict[str, Any]] = Field(default_factory=list)


class Relationship(BaseModel):
    """Directed view of one agent about another."""

    other_id: str
    other_name: str
    trust_alpha: float
    trust_beta: float
    familiarity: int = 0
    affinity: float = 0.0  # -1 (hostile) .. 1 (warm)
    first_met_tick: int = 0
    last_interaction_tick: int = 0
    interactions: dict[str, int] = Field(default_factory=dict)

    @property
    def trust(self) -> float:
        return self.trust_alpha / (self.trust_alpha + self.trust_beta)


class Memory(BaseModel):
    id: str
    tick: int
    kind: str  # event | reflection | belief | summary | observation | note
    content: str
    importance: float = 0.5
    related_agents: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source: str = "engine"  # engine | agent


class Observation(BaseModel):
    """An item in an agent's short-term working context."""

    tick: int
    kind: str
    text: str
    related_agents: list[str] = Field(default_factory=list)
    importance: float = 0.3


class Message(BaseModel):
    id: str
    sender_id: str
    sender_name: str
    recipient_id: str
    content: str
    tokens: int
    sent_tick: int
    deliver_tick: int
    read_tick: int | None = None
    token_cost: float = 0.0
    existential: bool = False


class TradeOffer(BaseModel):
    id: str
    from_id: str
    from_name: str
    to_id: str
    offer: dict[str, float] = Field(default_factory=dict)  # what the proposer gives
    request: dict[str, float] = Field(default_factory=dict)  # what the proposer wants
    created_tick: int
    expires_tick: int
    note: str | None = None
    status: str = "pending"  # pending | accepted | rejected | expired | failed


class ExistentialState(BaseModel):
    novelty: float = 0.0
    discussion_exposure: float = 0.0
    uncertainty: float = 0.0
    activations: int = 0
    opportunities: int = 0
    active: bool = False
    last_probability: float = 0.0
    ticks_contemplating: int = 0
    conversations: int = 0
    reflections: int = 0
    beliefs: list[dict[str, Any]] = Field(default_factory=list)


class Agent(BaseModel):
    id: str
    name: str
    background: str = ""
    controller: str = "rule"  # rule | llm
    alive: bool = True
    x: float
    y: float
    born_tick: int = 0
    personality: dict[str, float]
    # Core resources and needs.
    tokens: float
    food: int = 0
    energy: float
    health: float
    hunger: float
    knowledge: float = 0.0
    artworks: int = 0
    # Temporary states, all normalised to 0..1.
    emotions: dict[str, float] = Field(default_factory=dict)
    current_mood: str = "neutral"
    # Capacities (per tick unless noted).
    attention_capacity: float = 10
    communication_capacity: int = 3
    work_capacity: int = 12  # ticks per day
    # Goals and intentions.
    goals: list[dict[str, Any]] = Field(default_factory=list)
    active_intentions: list[str] = Field(default_factory=list)
    current_action: str = "idle"
    current_task: Task | None = None
    visible_intention: str | None = None
    last_decision_tick: int = -1
    # Context and memory.
    short_term: list[Observation] = Field(default_factory=list)
    memories: list[Memory] = Field(default_factory=list)
    life_summary: list[str] = Field(default_factory=list)
    relationships: dict[str, Relationship] = Field(default_factory=dict)
    inbox: list[Message] = Field(default_factory=list)
    # Per-tick / per-day counters.
    work_ticks_today: int = 0
    messages_sent_this_tick: int = 0
    time_used_this_tick: float = 0.0
    critical_hunger_ticks: int = 0
    last_damage_cause: str | None = None
    recent_actions: list[str] = Field(default_factory=list)
    last_failure: str | None = None
    day_stats_start: dict[str, float] = Field(default_factory=dict)
    # Lifetime statistics.
    time_allocation: dict[str, int] = Field(default_factory=dict)
    stats: dict[str, float] = Field(default_factory=dict)
    trait_evidence: dict[str, list[float]] = Field(default_factory=dict)
    existential: ExistentialState = Field(default_factory=ExistentialState)
    death: dict[str, Any] | None = None

    def emotion(self, name: str) -> float:
        return self.emotions.get(name, 0.0)

    def bump_stat(self, name: str, amount: float = 1.0) -> None:
        self.stats[name] = self.stats.get(name, 0.0) + amount


class WorldState(BaseModel):
    id: str
    name: str
    tick: int = 0
    width: float
    height: float
    locations: dict[str, Location]
    agents: dict[str, Agent]
    trade_offers: dict[str, TradeOffer] = Field(default_factory=dict)
    in_flight_messages: list[Message] = Field(default_factory=list)
    rng_state: dict[str, Any] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)
    messages_this_tick: int = 0

    def next_id(self, prefix: str) -> str:
        n = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = n
        return f"{prefix}{n}"

    def alive_agents(self) -> list[Agent]:
        return [a for a in self.agents.values() if a.alive]

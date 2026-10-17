"""Typed simulation configuration.

Every tunable number in the simulation lives here so that business logic never
hardcodes experimental parameters. Section names and keys follow the project
specification (section 23); additional sections extend it with the rules the
engine needs. All values are abstract simulation units.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SimulationSection(_Section):
    ticks_per_day: int = Field(24, ge=1)
    max_agents: int = Field(20, ge=1, le=1000)
    population: int = Field(5, ge=1, le=1000)
    random_seed: int = 42
    decision_timeout_seconds: float = Field(20.0, gt=0, le=600)
    fallback_on_timeout: bool = True
    # Stop automatically after this many ticks (None = run until paused).
    max_ticks: int | None = None
    # Persist a full world snapshot every N ticks (events are always persisted).
    snapshot_interval_ticks: int = Field(1, ge=1)
    # Death is permanent unless an experiment explicitly enables replacement.
    enable_replacement: bool = False


class LocationSpec(_Section):
    name: str
    type: Literal["workplace", "food", "rest", "gathering", "wild"]
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


class WorldSection(_Section):
    width: float = 100.0
    height: float = 100.0
    # Explicit layout; when empty a layout is generated from the counts below.
    locations: list[LocationSpec] = Field(default_factory=list)
    workplaces: int = 2
    food_sources: int = 2
    rest_areas: int = 2
    gathering_areas: int = 1
    workplace_capacity: int = 6
    food_stock_per_source: int = 40
    food_restock_per_day: int = 40
    perception_radius: float = 18.0
    interaction_radius: float = 8.0
    movement_speed_per_tick: float = 40.0
    movement_energy_per_unit: float = 0.05
    explore_distance: float = 25.0
    explore_discovery_probability: float = 0.15
    explore_discovery_tokens: float = 3.0
    explore_hazard_probability: float = 0.03
    hazard_damage: float = 15.0
    # Background environmental hazard per agent per tick (0 disables).
    ambient_hazard_probability: float = 0.0


class ResourcesSection(_Section):
    starting_tokens: float = 20
    starting_energy: float = 100
    starting_health: float = 100
    starting_hunger: float = 0
    starting_food: int = 0
    maximum_energy: float = 100
    maximum_health: float = 100
    maximum_hunger: float = 100
    maximum_food_inventory: int = 10
    food_price: float = 3
    food_nutrition: float = 30
    hunger_increase_per_tick: float = 4
    # Hunger at/above this level damages health every tick.
    critical_hunger: float = 80
    starvation_damage_per_tick: float = 4
    # Death if hunger stays critical for longer than this many ticks.
    max_critical_hunger_ticks: int = 48
    passive_energy_drain_per_tick: float = 1
    exhaustion_damage_per_tick: float = 3
    rest_energy_recovery_per_tick: float = 20
    rest_area_recovery_multiplier: float = 1.5
    rest_health_recovery_per_tick: float = 3
    natural_health_recovery_per_tick: float = 0.5
    # Health only recovers while hunger is below this level.
    health_recovery_max_hunger: float = 50
    # Fixed per-day upkeep in tokens (0 disables).
    daily_upkeep: float = 0


class WorkSection(_Section):
    base_wage_per_tick: float = 5
    energy_cost_per_tick: float = 15
    safe_workload: float = 1.0
    health_penalty_rate: float = 2
    max_work_ticks_per_day: int = 12
    overtime_after_ticks_per_day: int = 8
    overtime_workload_increment: float = 0.25
    fatigue_energy_threshold: float = 30
    fatigue_workload_multiplier: float = 1.5
    low_energy_productivity: float = 0.6
    knowledge_productivity_per_point: float = 0.01
    max_productivity_bonus: float = 0.25


class CapacitySection(_Section):
    actions_per_tick: int = 1
    max_message_tokens: int = Field(100, ge=1, le=2000)
    max_outgoing_messages_per_tick: int = 3
    max_incoming_messages_processed_per_tick: int = 5
    attention_budget_per_tick: float = 10
    context_token_budget: int = Field(6000, ge=500, le=100000)
    max_task_duration_ticks: int = 4
    max_rest_duration_ticks: int = 8
    max_active_goals: int = 3
    decision_attention_cost: float = 2
    message_attention_cost: float = 1
    offer_attention_cost: float = 1
    observation_attention_cost: float = 0.5
    # Unread messages older than this are dropped from the inbox.
    message_expiry_ticks: int = 24
    inbox_capacity: int = 20
    # Memory store limits (oldest low-importance memories are consolidated).
    max_memories_per_agent: int = 120
    short_term_capacity: int = 20
    # Relative random variation of individual capacities (0 = identical agents).
    capacity_variation: float = 0.0


class CommunicationSection(_Section):
    enabled: bool = True
    base_token_cost: float = 0.1
    token_cost_per_message_token: float = 0.001
    distance_cost_per_unit: float = 0.01
    interference_cost: float = 0.01
    base_processing_time: float = 0.05
    sender_energy_per_token: float = 0.001
    receiver_energy_per_token: float = 0.001
    minimum_bandwidth: float = 1
    # Message tokens an agent can transmit per tick of time.
    bandwidth_tokens_per_tick: float = 200
    # Messages are delivered at the start of the tick after they are sent.
    delivery_delay_ticks: int = 1


class SocialSection(_Section):
    allow_theft: bool = True
    theft_base_success: float = 0.5
    theft_detection_probability: float = 0.6
    theft_max_tokens: float = 5
    trade_offer_expiry_ticks: int = 6
    socialize_loneliness_relief: float = 0.25
    loneliness_increase_per_tick: float = 0.01


class TrustSection(_Section):
    prior_alpha: float = 2
    prior_beta: float = 2
    maximum_evidence_weight: float = 1.0
    enable_time_decay: bool = False
    # Fraction of the distance to the prior recovered per day when decay is on.
    decay_rate_per_day: float = 0.05


class PersonalitySection(_Section):
    initial_default: float = 0.5
    # How initial traits are drawn: "default" gives every agent the same values
    # (initial_default or trait_means); "normal" draws with standard deviation
    # initial_spread; "uniform" draws within +/- initial_spread of the mean.
    initial_distribution: Literal["default", "normal", "uniform"] = "normal"
    initial_spread: float = Field(0.15, ge=0, le=0.5)
    # Explicit per-trait mean overrides, e.g. {"spirituality": 0.8}.
    trait_means: dict[str, float] = Field(default_factory=dict)
    learning_rate: float = 0.02
    maximum_change_per_event: float = 0.02
    # Total evidence weight at which accumulated evidence counts fully.
    evidence_saturation: float = 3.0
    # Trait updates are applied from accumulated evidence once per period.
    update_interval_ticks: int = 24


class ExistentialSection(_Section):
    enabled: bool = True
    base_probability: float = 0.02
    spirituality_coefficient: float = 0.12
    novelty_coefficient: float = 0.05
    stress_coefficient: float = 0.06
    social_discussion_coefficient: float = 0.08
    free_time_coefficient: float = 0.05
    overload_coefficient: float = 0.08
    minimum_probability: float = 0.005
    maximum_probability: float = 0.30
    # Per-tick decay of the novelty and discussion-exposure signals.
    signal_decay_per_tick: float = 0.05


class LLMSection(_Section):
    # anthropic: Anthropic API key · openrouter: OpenRouter API key (many vendors' models)
    # claude_code: the local Claude Code CLI and its subscription login · mock: offline · none: rules only.
    provider: Literal["anthropic", "openrouter", "claude_code", "mock", "none"] = "none"
    # Model ID for the provider: an Anthropic ID (cheaper models such as claude-haiku-5-5 cut cost
    # for large populations), an OpenRouter ID ("vendor/model"), or a Claude Code alias
    # ("sonnet", "haiku", "opus") or full ID.
    model: str = Field("claude-opus-5-5", min_length=1, max_length=120)
    # Claude subscription mode: "per_agent" keeps one Claude Code conversation per agent
    # (--session-id, then --resume); "fresh" starts a new unsaved one for every decision.
    claude_code_session_mode: Literal["per_agent", "fresh"] = "per_agent"
    # How many agents are LLM-controlled; the rest use the rule-based policy.
    # None means all agents.
    llm_agents: int | None = None
    max_output_tokens: int = Field(800, ge=64, le=16000)
    # Reasoning effort (low | medium | high | xhigh | max); None uses the model default.
    effort: str | None = "low"
    # Retry policy-declined requests on Anthropic's recommended fallback model.
    server_side_fallback: bool = True
    # Cache the shared, static part of the prompt across agents and ticks.
    prompt_caching: bool = True
    max_concurrent_requests: int = Field(5, ge=1, le=100)
    max_retries: int = 1
    request_timeout_seconds: float = 30
    requests_per_minute: int = 50
    # Backpressure: at most this many LLM decisions are requested per tick;
    # the rest get the rule-based fallback.
    max_queue_size: int = 50
    # Spend caps in USD (None = unlimited). When reached, agents fall back to rules.
    maximum_world_spend: float | None = 5.0
    maximum_agent_daily_spend: float | None = 0.5
    # Price per million tokens in USD for cost estimates (None = built-in table).
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None
    # Mock provider fault injection (for tests and offline demos).
    mock_latency_seconds: float = 0.0
    mock_failure_rate: float = 0.0
    mock_invalid_output_rate: float = 0.0
    mock_seed: int = 0


class ChronicleSection(_Section):
    """The daily storyline (see aisim/analysis/chronicle.py)."""

    enabled: bool = True
    # auto: the world's LLM writes each day's storyline when the world uses one
    # (anthropic, openrouter, claude_code), otherwise the built-in template does;
    # template: never use the LLM; llm: same as auto (kept explicit for configs).
    narrator: Literal["auto", "template", "llm"] = "auto"
    max_output_tokens: int = Field(1500, ge=200, le=8000)


class SimulationConfig(_Section):
    name: str = "default"
    description: str = ""
    # Optional resource-abundance level (see config/levels.py); derives prices,
    # wages, jobs and food supply relative to the population.
    resource_level: Literal["very_scarce", "scarce", "almost_scarce", "normal", "almost_abundant", "abundant",
                            "very_abundant"] | None = None
    simulation: SimulationSection = Field(default_factory=SimulationSection)
    world: WorldSection = Field(default_factory=WorldSection)
    resources: ResourcesSection = Field(default_factory=ResourcesSection)
    work: WorkSection = Field(default_factory=WorkSection)
    capacity: CapacitySection = Field(default_factory=CapacitySection)
    communication: CommunicationSection = Field(default_factory=CommunicationSection)
    social: SocialSection = Field(default_factory=SocialSection)
    trust: TrustSection = Field(default_factory=TrustSection)
    personality: PersonalitySection = Field(default_factory=PersonalitySection)
    existential_goal: ExistentialSection = Field(default_factory=ExistentialSection)
    llm: LLMSection = Field(default_factory=LLMSection)
    chronicle: ChronicleSection = Field(default_factory=ChronicleSection)

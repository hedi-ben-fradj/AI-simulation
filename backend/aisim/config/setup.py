"""User-facing world setup settings (the frontend's setup page).

These are friendly, bounded choices that map onto the full configuration via
:func:`settings_to_overrides`, so every world created this way still records its
complete resolved configuration.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from ..engine.state import TRAITS
from .levels import LEVEL_IDS

ResourceLevel = Literal["very_scarce", "scarce", "almost_scarce", "normal", "almost_abundant", "abundant",
                        "very_abundant"]

COMMUNICATION_COSTS: dict[str, dict[str, float]] = {
    "free": {"base_token_cost": 0.0, "token_cost_per_message_token": 0.0, "distance_cost_per_unit": 0.0,
             "interference_cost": 0.0},
    "cheap": {"base_token_cost": 0.02, "token_cost_per_message_token": 0.0005, "distance_cost_per_unit": 0.002,
              "interference_cost": 0.005},
    "normal": {"base_token_cost": 0.1, "token_cost_per_message_token": 0.001, "distance_cost_per_unit": 0.01,
               "interference_cost": 0.01},
    "expensive": {"base_token_cost": 0.8, "token_cost_per_message_token": 0.005, "distance_cost_per_unit": 0.05,
                  "interference_cost": 0.05},
}
TRUST_PRIORS: dict[str, tuple[float, float]] = {
    "trusting": (4.0, 1.5), "neutral": (2.0, 2.0), "suspicious": (1.5, 4.0),
}
HAZARDS: dict[str, tuple[float, float]] = {  # (ambient per tick, while exploring)
    "none": (0.0, 0.0), "low": (0.0, 0.03), "high": (0.005, 0.08),
}
WORLD_SIZES: dict[str, float] = {"compact": 60.0, "normal": 100.0, "large": 140.0}

# Model per provider when the setup page leaves it empty, and the suggestions it offers.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-5-5",
    "openrouter": "google/gemini-2.5-flash",
    "claude_code": "sonnet",
}
MODEL_SUGGESTIONS: dict[str, list[str]] = {
    "anthropic": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
    "openrouter": ["google/gemini-2.5-flash", "anthropic/claude-haiku-4.5", "anthropic/claude-sonnet-4.5"],
    "claude_code": ["sonnet", "haiku", "opus"],
}


class SetupSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=200)
    population: int = Field(5, ge=2, le=50)
    resource_level: ResourceLevel = "normal"
    # Personality: "identical" gives every agent the same traits (50% unless
    # trait_means says otherwise); "random" varies traits around the means.
    personality_mode: Literal["identical", "random"] = "random"
    personality_deviation: float = Field(0.15, ge=0.0, le=0.5)
    personality_distribution: Literal["normal", "uniform"] = "normal"
    trait_means: dict[str, float] = Field(default_factory=dict)
    days: int | None = Field(None, ge=1, le=365)
    seed: int = Field(42, ge=0, le=2**31 - 1)
    world_size: Literal["auto", "compact", "normal", "large"] = "auto"
    communication_cost: Literal["free", "cheap", "normal", "expensive"] = "normal"
    trust_prior: Literal["trusting", "neutral", "suspicious"] = "neutral"
    allow_theft: bool = True
    hazards: Literal["none", "low", "high"] = "low"
    replace_dead: bool = False
    existential_goal: bool = True
    # none = rule-based · mock = offline LLM pipeline · anthropic / openrouter = API key ·
    # claude_code = Claude subscription through the local Claude Code CLI.
    provider: Literal["none", "mock", "anthropic", "openrouter", "claude_code"] = "none"
    # Key for this world only (anthropic / openrouter). Kept in server memory, never stored
    # with the world's configuration; empty means "use the server's environment variable".
    api_key: SecretStr | None = Field(None, max_length=400)
    llm_agents: int | None = Field(None, ge=0, le=50)
    model: str | None = Field(None, max_length=120)
    effort: Literal["low", "medium", "high"] | None = None
    max_world_spend: float | None = Field(None, ge=0, le=1000)
    claude_session_mode: Literal["per_agent", "fresh"] = "per_agent"
    # Who writes the daily storyline: the world's LLM when it has one (auto), or the built-in template.
    chronicle_narrator: Literal["auto", "template"] = "auto"
    # Seconds a tick waits for decisions (the CLI needs longer than an API call).
    decision_timeout: float | None = Field(None, ge=5, le=600)
    start: bool = True

    @field_validator("trait_means")
    @classmethod
    def _check_traits(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = set(v) - set(TRAITS)
        if unknown:
            raise ValueError(f"unknown trait(s): {', '.join(sorted(unknown))}")
        for trait, value in v.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{trait} mean must be between 0 and 1")
        return v


def _world_size(settings: SetupSettings) -> float:
    if settings.world_size != "auto":
        return WORLD_SIZES[settings.world_size]
    if settings.population <= 4:
        return WORLD_SIZES["compact"]
    return WORLD_SIZES["normal"] if settings.population <= 12 else WORLD_SIZES["large"]


def settings_to_overrides(s: SetupSettings) -> dict[str, Any]:
    alpha, beta = TRUST_PRIORS[s.trust_prior]
    ambient, explore = HAZARDS[s.hazards]
    size = _world_size(s)
    overrides: dict[str, Any] = {
        "resource_level": s.resource_level,
        "simulation": {
            "population": s.population,
            "max_agents": max(20, s.population),
            "random_seed": s.seed,
            "max_ticks": s.days * 24 if s.days else None,
            "enable_replacement": s.replace_dead,
        },
        "world": {
            "width": size, "height": size,
            "ambient_hazard_probability": ambient, "explore_hazard_probability": explore,
        },
        "personality": {
            "initial_default": 0.5,
            "initial_distribution": "default" if s.personality_mode == "identical" else s.personality_distribution,
            "initial_spread": 0.0 if s.personality_mode == "identical" else s.personality_deviation,
            "trait_means": dict(s.trait_means),
        },
        "communication": dict(COMMUNICATION_COSTS[s.communication_cost]),
        "trust": {"prior_alpha": alpha, "prior_beta": beta},
        "social": {"allow_theft": s.allow_theft},
        "existential_goal": {"enabled": s.existential_goal},
        "llm": {"provider": s.provider, "llm_agents": s.llm_agents},
        "chronicle": {"narrator": s.chronicle_narrator},
    }
    llm = overrides["llm"]
    llm["model"] = s.model or DEFAULT_MODELS.get(s.provider, "claude-opus-5-5")
    if s.effort:
        llm["effort"] = s.effort
    if s.max_world_spend is not None:
        llm["maximum_world_spend"] = s.max_world_spend
    timeout = s.decision_timeout
    if s.provider == "claude_code":
        # Each decision starts a CLI process; keep a few in flight and wait longer for them.
        llm["claude_code_session_mode"] = s.claude_session_mode
        llm["max_concurrent_requests"] = 3
        llm["maximum_world_spend"] = None  # covered by the subscription, nothing is billed here
        llm["maximum_agent_daily_spend"] = None
        timeout = timeout or 120.0
    elif s.provider == "openrouter":
        timeout = timeout or 45.0
    if timeout:
        overrides["simulation"]["decision_timeout_seconds"] = timeout
    return overrides


def setup_options() -> dict[str, Any]:
    from .levels import RESOURCE_LEVELS

    return {
        "resource_levels": RESOURCE_LEVELS,
        "level_ids": LEVEL_IDS,
        "communication_costs": list(COMMUNICATION_COSTS),
        "trust_priors": list(TRUST_PRIORS),
        "hazards": list(HAZARDS),
        "world_sizes": ["auto", *WORLD_SIZES],
        "traits": list(TRAITS),
        "models": MODEL_SUGGESTIONS["anthropic"],
        "model_suggestions": MODEL_SUGGESTIONS,
        "default_models": DEFAULT_MODELS,
        "defaults": SetupSettings().model_dump(),
    }

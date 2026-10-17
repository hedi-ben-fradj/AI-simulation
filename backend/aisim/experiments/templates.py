"""Ready-made experiment designs from the specification (section 22.4)."""

from __future__ import annotations

from typing import Any

from ..config.levels import LEVEL_IDS

TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "scarcity_vs_abundance",
        "name": "Scarcity vs abundance",
        "description": "Same population, different resource environments. Compare survival, work, social life and contemplation.",
        "base_preset": "default",
        "conditions": [
            {"name": "abundant", "overrides": {"resource_level": "abundant"}},
            {"name": "normal", "overrides": {"resource_level": "normal"}},
            {"name": "scarce", "overrides": {"resource_level": "scarce"}},
        ],
        "seeds": [1, 2, 3, 4, 5],
        "ticks": 168,
    },
    {
        "id": "resource_gradient",
        "name": "Resource gradient (7 levels)",
        "description": "Every resource level from very scarce to very abundant. How do survival, work, social "
                       "life and contemplation change along the gradient?",
        "base_preset": "default",
        "conditions": [{"name": lv, "overrides": {"resource_level": lv}} for lv in LEVEL_IDS],
        "seeds": [1, 2, 3],
        "ticks": 168,
    },
    {
        "id": "seed_variation",
        "name": "Same world, different seeds",
        "description": "Measures run-to-run variability of a single configuration.",
        "base_preset": "default",
        "conditions": [{"name": "default", "overrides": {}}],
        "seeds": list(range(1, 11)),
        "ticks": 168,
    },
    {
        "id": "communication_cost",
        "name": "Communication cost",
        "description": "Cheap vs expensive messaging. Does cost shrink social networks?",
        "base_preset": "default",
        "conditions": [
            {"name": "cheap", "overrides": {"communication": {"base_token_cost": 0.01, "distance_cost_per_unit": 0.0}}},
            {"name": "default", "overrides": {}},
            {"name": "expensive", "overrides": {"communication": {"base_token_cost": 1.0, "distance_cost_per_unit": 0.05}}},
        ],
        "seeds": [1, 2, 3, 4, 5],
        "ticks": 168,
    },
    {
        "id": "trust_priors",
        "name": "Trust priors",
        "description": "Agents start trusting, neutral or suspicious (Beta prior).",
        "base_preset": "default",
        "conditions": [
            {"name": "trusting", "overrides": {"trust": {"prior_alpha": 4, "prior_beta": 1}}},
            {"name": "neutral", "overrides": {}},
            {"name": "suspicious", "overrides": {"trust": {"prior_alpha": 1, "prior_beta": 4}}},
        ],
        "seeds": [1, 2, 3, 4, 5],
        "ticks": 168,
    },
    {
        "id": "spirituality",
        "name": "Spirituality distribution",
        "description": "Low vs high mean spirituality. Does it change how often agents contemplate their purpose?",
        "base_preset": "abundance",
        "conditions": [
            {"name": "low", "overrides": {"personality": {"trait_means": {"spirituality": 0.15}}}},
            {"name": "medium", "overrides": {}},
            {"name": "high", "overrides": {"personality": {"trait_means": {"spirituality": 0.85}}}},
        ],
        "seeds": [1, 2, 3, 4, 5],
        "ticks": 168,
    },
    {
        "id": "attention_capacity",
        "name": "Attention capacity",
        "description": "Limited vs ample attention per decision (messages read, overload, contemplation).",
        "base_preset": "default",
        "conditions": [
            {"name": "low", "overrides": {"capacity": {"attention_budget_per_tick": 4}}},
            {"name": "default", "overrides": {}},
            {"name": "high", "overrides": {"capacity": {"attention_budget_per_tick": 20}}},
        ],
        "seeds": [1, 2, 3, 4, 5],
        "ticks": 168,
    },
]

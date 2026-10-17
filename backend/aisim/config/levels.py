"""Resource-abundance levels, from very scarce to very abundant.

A level sets prices, wages, starting money, jobs and the food supply. Food
supply and job counts are expressed *relative to the population's needs*, so a
level means the same thing for 2 agents as for 20:

    meals needed per agent per day = hunger_increase_per_tick * ticks_per_day / food_nutrition
    food restocked per day         = supply_ratio * meals needed * population
    work slots                     = job_ratio * population

A supply ratio below 1 means there is not enough food for everyone even if
everyone can pay; above 1 leaves a surplus.
"""

from __future__ import annotations

import math
from typing import Any

# id, label, supply_ratio, meal price, wage per tick, starting tokens, job_ratio,
# food sources, chance to discover something while exploring
_LEVELS = [
    ("very_scarce", "Very scarce", 0.70, 8.0, 3.0, 5, 0.35, 1, 0.08),
    ("scarce", "Scarce", 0.85, 6.0, 4.0, 8, 0.50, 1, 0.10),
    ("almost_scarce", "Almost scarce", 0.95, 4.5, 4.5, 12, 0.70, 1, 0.12),
    ("normal", "Normal", 1.30, 3.0, 5.0, 20, 1.00, 2, 0.15),
    ("almost_abundant", "Almost abundant", 1.60, 2.5, 6.0, 28, 1.00, 2, 0.18),
    ("abundant", "Abundant", 2.20, 1.5, 8.0, 40, 1.00, 3, 0.20),
    ("very_abundant", "Very abundant", 3.00, 1.0, 10.0, 60, 1.00, 3, 0.25),
]

RESOURCE_LEVELS: list[dict[str, Any]] = [
    {"id": i, "label": label, "supply_ratio": supply, "food_price": price, "wage": wage, "starting_tokens": tokens,
     "job_ratio": jobs, "food_sources": sources, "discovery_probability": discovery}
    for i, label, supply, price, wage, tokens, jobs, sources, discovery in _LEVELS
]
LEVEL_IDS = [lvl["id"] for lvl in RESOURCE_LEVELS]
_BY_ID = {lvl["id"]: lvl for lvl in RESOURCE_LEVELS}


def meals_needed_per_day(data: dict[str, Any]) -> float:
    rc = data.get("resources", {})
    tpd = data.get("simulation", {}).get("ticks_per_day", 24)
    return rc.get("hunger_increase_per_tick", 4) * tpd / rc.get("food_nutrition", 30)


def resource_overrides(level: str, data: dict[str, Any]) -> dict[str, Any]:
    """Config overrides for ``level`` given the (merged) raw config ``data``."""
    if level not in _BY_ID:
        raise ValueError(f"unknown resource level '{level}' (choose from {', '.join(LEVEL_IDS)})")
    lvl = _BY_ID[level]
    population = max(1, int(data.get("simulation", {}).get("population", 5)))
    sources = lvl["food_sources"]
    restock_total = max(1, round(lvl["supply_ratio"] * meals_needed_per_day(data) * population))
    per_source = max(1, math.ceil(restock_total / sources))
    workplaces = 1 if lvl["job_ratio"] < 1 else 2
    capacity = max(1, math.ceil(lvl["job_ratio"] * population / workplaces))
    return {
        "world": {
            "food_sources": sources,
            "food_restock_per_day": per_source,
            "food_stock_per_source": max(per_source, math.ceil(per_source * 1.5)),
            "workplaces": workplaces,
            "workplace_capacity": capacity,
            "explore_discovery_probability": lvl["discovery_probability"],
        },
        "resources": {"food_price": lvl["food_price"], "starting_tokens": lvl["starting_tokens"]},
        "work": {"base_wage_per_tick": lvl["wage"]},
    }


def describe_economy(config) -> dict[str, Any]:
    """Human-readable consequences of a resolved config (for the setup preview)."""
    rc, wc, w, sim = config.resources, config.work, config.world, config.simulation
    population = sim.population
    meals = rc.hunger_increase_per_tick * sim.ticks_per_day / rc.food_nutrition
    supply = w.food_restock_per_day * w.food_sources
    daily_food_cost = meals * rc.food_price
    work_ticks_needed = daily_food_cost / wc.base_wage_per_tick if wc.base_wage_per_tick else float("inf")
    return {
        "population": population,
        "meals_needed_per_agent_per_day": round(meals, 2),
        "food_supply_per_day": supply,
        "food_supply_vs_need": round(supply / (meals * population), 2) if population else None,
        "meal_price": rc.food_price,
        "wage_per_tick": wc.base_wage_per_tick,
        "daily_food_cost": round(daily_food_cost, 2),
        "work_hours_for_food_per_day": round(work_ticks_needed * 24 / sim.ticks_per_day, 1),
        "work_slots": w.workplaces * w.workplace_capacity,
        "starting_tokens": rc.starting_tokens,
        "days_of_food_from_savings": round(rc.starting_tokens / daily_food_cost, 1) if daily_food_cost else None,
    }

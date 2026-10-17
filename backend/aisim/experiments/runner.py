"""Execute single experiment runs and summarise them into comparable measures."""

from __future__ import annotations

import asyncio
import threading
import uuid
from statistics import mean
from typing import Any

from ..config import SimulationConfig, deep_merge, load_config
from ..engine.simulation import Simulation, TickResult
from .spec import Condition, ExperimentSpec

# Activity groups used for time-allocation comparisons (research question:
# how agents split time between work, rest, social life, creativity and contemplation).
TIME_GROUPS = {
    "work": ("work",),
    "rest": ("rest",),
    "survival_chores": ("eat", "buy_food"),
    "social": ("socialize", "talk", "give", "offer_trade", "accept_trade", "reject_trade"),
    "creative_scientific": ("create", "study", "explore"),
    "contemplation": ("reflect",),
    "conflict": ("steal",),
    "travel_idle": ("travel", "move", "idle"),
}

SUMMARY_METRICS = [
    "survival_rate", "deaths", "mean_health", "mean_energy", "mean_hunger", "final_tokens_mean", "final_gini",
    "share_work", "share_rest", "share_survival_chores", "share_social", "share_creative_scientific",
    "share_contemplation", "share_conflict", "share_travel_idle",
    "messages_per_agent_day", "trades_per_agent_day", "gifts_per_agent_day", "thefts_per_agent_day",
    "refusals_per_agent_day", "final_trust_mean", "final_friendships", "final_network_density",
    "existential_activation_rate", "existential_reflections_per_agent_day", "happiness_mean", "stress_mean",
    "llm_spend_usd", "invalid_decision_rate",
]


def build_run_config(spec: ExperimentSpec, condition: Condition, seed: int) -> tuple[str, SimulationConfig]:
    preset = condition.preset or spec.base_preset
    overrides = deep_merge(spec.base_overrides, condition.overrides)
    overrides = deep_merge(overrides, {"simulation": {"random_seed": seed, "max_ticks": spec.ticks}})
    config = load_config(preset, overrides)
    config = config.model_copy(update={"name": f"{spec.name} · {condition.name} · seed {seed}"})
    return preset, config


def summarise_run(sim: Simulation, metrics: list[dict[str, Any]], decisions: int, invalid: int,
                  llm_spend: float) -> dict[str, Any]:
    agents = list(sim.world.agents.values())
    tpd = sim.config.simulation.ticks_per_day
    population = len(agents)
    alive = [a for a in agents if a.alive]
    alloc: dict[str, int] = {}
    for a in agents:
        for k, v in a.time_allocation.items():
            alloc[k] = alloc.get(k, 0) + v
    total_ticks = sum(alloc.values()) or 1
    agent_days = max(1e-9, total_ticks / tpd)
    s = lambda key: sum(m.get(key, 0) for m in metrics)  # noqa: E731
    last = metrics[-1] if metrics else {}
    opps = sum(a.existential.opportunities for a in agents)
    out: dict[str, Any] = {
        "ticks": sim.world.tick,
        "population": population,
        "survival_rate": len(alive) / population if population else 0.0,
        "deaths": population - len(alive),
        "deaths_by_cause": last.get("deaths_by_cause", {}),
        "mean_health": mean(m["health_mean"] for m in metrics) if metrics else 0.0,
        "mean_energy": mean(m["energy_mean"] for m in metrics) if metrics else 0.0,
        "mean_hunger": mean(m["hunger_mean"] for m in metrics) if metrics else 0.0,
        "happiness_mean": mean(m["happiness_mean"] for m in metrics) if metrics else 0.0,
        "stress_mean": mean(m["stress_mean"] for m in metrics) if metrics else 0.0,
        "final_tokens_mean": last.get("tokens_mean", 0.0),
        "final_gini": last.get("tokens_gini", 0.0),
        "messages_per_agent_day": s("messages_sent") / agent_days,
        "trades_per_agent_day": (s("trades") + s("help_given")) / agent_days,
        "gifts_per_agent_day": s("gifts") / agent_days,
        "thefts_per_agent_day": s("thefts") / agent_days,
        "refusals_per_agent_day": s("refusals") / agent_days,
        "final_trust_mean": last.get("trust_mean", 0.0),
        "final_friendships": last.get("friendships", 0),
        "final_network_density": last.get("network_density", 0.0),
        "existential_activation_rate": sum(a.existential.activations for a in agents) / opps if opps else 0.0,
        "existential_reflections_per_agent_day": s("existential_reflections") / agent_days,
        "llm_spend_usd": llm_spend,
        "invalid_decision_rate": invalid / decisions if decisions else 0.0,
    }
    for group, acts in TIME_GROUPS.items():
        out[f"share_{group}"] = sum(alloc.get(a, 0) for a in acts) / total_ticks
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in out.items()}


def daily_series(metrics: list[dict[str, Any]], tpd: int) -> list[dict[str, Any]]:
    """End-of-day snapshot of key series (for overlay charts)."""
    out = []
    for m in metrics:
        if (m["tick"] + 1) % tpd == 0 or m is metrics[-1]:
            out.append({"day": round((m["tick"] + 1) / tpd, 3), "alive": m["alive"], "tokens_mean": m["tokens_mean"],
                        "health_mean": m["health_mean"], "trust_mean": m["trust_mean"],
                        "happiness_mean": m["happiness_mean"]})
    return out


class RunCancelled(Exception):
    pass


def run_rule_based(config: SimulationConfig, repo, experiment_id: str | None, condition: str,
                   preset: str, cancel: threading.Event | None = None, progress=None) -> dict[str, Any]:
    """Synchronous run (rule-based agents); safe to execute in a worker thread."""
    sim = Simulation.create(config, uuid.uuid4().hex[:12])
    if repo is not None:
        repo.create_world(sim, preset, experiment_id=experiment_id, condition=condition)
    metrics: list[dict[str, Any]] = []
    decisions = invalid = 0
    for _ in range(config.simulation.max_ticks or 0):
        if cancel is not None and cancel.is_set():
            raise RunCancelled()
        if not sim.world.alive_agents():
            break
        result: TickResult = sim.step()
        metrics.append(result.metrics)
        decisions += len(result.decisions)
        invalid += sum(1 for d in result.decisions if not d.valid)
        if repo is not None:
            done = sim.world.tick >= (config.simulation.max_ticks or 0) or not sim.world.alive_agents()
            repo.save_tick(sim, result, status="finished" if done else "running", force_snapshot=done)
        if progress:
            progress()
    if repo is not None:
        repo.set_status(sim.world.id, "finished")
    return {"world_id": sim.world.id, "summary": summarise_run(sim, metrics, decisions, invalid, 0.0),
            "daily": daily_series(metrics, config.simulation.ticks_per_day)}


async def run_with_llm(config: SimulationConfig, repo, experiment_id: str | None, condition: str, preset: str,
                       cancel: threading.Event | None = None, progress=None) -> dict[str, Any]:
    from ..agents.service import LLMDecider

    sim = Simulation.create(config, uuid.uuid4().hex[:12])
    decider = LLMDecider.from_config(config, sim.world.id)
    if repo is not None:
        await asyncio.to_thread(repo.create_world, sim, preset, experiment_id, condition)
    metrics: list[dict[str, Any]] = []
    decisions = invalid = 0
    try:
        for _ in range(config.simulation.max_ticks or 0):
            if cancel is not None and cancel.is_set():
                raise RunCancelled()
            if not sim.world.alive_agents():
                break
            requests = sim.begin_tick()
            proposals, meta = await decider.decide(sim, requests)
            sim.apply_decisions(proposals, meta)
            result = sim.advance()
            result.metrics["llm_spend_usd"] = decider.stats()["spend_usd"]
            metrics.append(result.metrics)
            decisions += len(result.decisions)
            invalid += sum(1 for d in result.decisions if not d.valid)
            if repo is not None:
                done = sim.world.tick >= (config.simulation.max_ticks or 0) or not sim.world.alive_agents()
                await asyncio.to_thread(repo.save_tick, sim, result, "finished" if done else "running",
                                        decider.drain_usage(), decider.stats()["spend_usd"], done)
            if progress:
                progress()
    finally:
        await decider.close()
    if repo is not None:
        await asyncio.to_thread(repo.set_status, sim.world.id, "finished")
    spend = decider.stats()["spend_usd"]
    return {"world_id": sim.world.id, "summary": summarise_run(sim, metrics, decisions, invalid, spend),
            "daily": daily_series(metrics, config.simulation.ticks_per_day)}

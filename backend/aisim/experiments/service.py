"""Runs experiments in the background and stores their results."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import threading
import uuid
from typing import Any

from ..persistence.repository import Repository
from .compare import compare, mean_daily_series
from .runner import SUMMARY_METRICS, RunCancelled, build_run_config, run_rule_based, run_with_llm
from .spec import ExperimentSpec

log = logging.getLogger(__name__)

TIMESERIES_KEYS = ["tick", "day", "alive", "deaths_total", "tokens_mean", "tokens_gini", "hunger_mean", "energy_mean",
                   "health_mean", "happiness_mean", "stress_mean", "loneliness_mean", "trust_mean", "friendships",
                   "network_density", "messages_sent", "trades", "help_given", "gifts", "thefts", "refusals",
                   "existential_activations", "existential_reflections", "food_stock_total", "llm_spend_usd"]


class ExperimentService:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.tasks: dict[str, asyncio.Task] = {}
        self.cancels: dict[str, threading.Event] = {}
        self.progress: dict[str, dict[str, int]] = {}

    # ------------------------------------------------------------------ control
    def recover_after_restart(self) -> None:
        for exp in self.repo.list_experiments():
            if exp["status"] in ("pending", "running"):
                self.repo.update_experiment(exp["id"], status="interrupted",
                                            error="backend restarted while the experiment was running")

    async def start(self, spec: ExperimentSpec) -> str:
        configs = {}
        for cond in spec.conditions:  # validate every condition before starting
            preset, cfg = build_run_config(spec, cond, spec.seeds[0])
            configs[cond.name] = {"preset": preset, "config": cfg.model_dump(mode="json")}
        exp_id = uuid.uuid4().hex[:12]
        stored = spec.model_dump(mode="json")
        stored["resolved_configs"] = configs
        await asyncio.to_thread(self.repo.create_experiment, exp_id, spec.name, spec.description, stored)
        self.cancels[exp_id] = threading.Event()
        self.progress[exp_id] = {"done_ticks": 0, "total_ticks": spec.ticks * len(spec.seeds) * len(spec.conditions)}
        self.tasks[exp_id] = asyncio.create_task(self._run(exp_id, spec), name=f"experiment-{exp_id}")
        return exp_id

    async def cancel(self, exp_id: str) -> bool:
        event = self.cancels.get(exp_id)
        if event is None:
            return False
        event.set()
        task = self.tasks.get(exp_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        return True

    async def shutdown(self) -> None:
        for event in self.cancels.values():
            event.set()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def wait(self, exp_id: str) -> None:
        task = self.tasks.get(exp_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    def live_progress(self, exp_id: str) -> float | None:
        p = self.progress.get(exp_id)
        if not p or not p["total_ticks"]:
            return None
        return min(1.0, p["done_ticks"] / p["total_ticks"])

    # ------------------------------------------------------------------ running
    async def _run(self, exp_id: str, spec: ExperimentSpec) -> None:
        cancel = self.cancels[exp_id]
        runs: list[dict[str, Any]] = [
            {"condition": c.name, "seed": seed, "status": "pending"} for c in spec.conditions for seed in spec.seeds]
        conditions = {c.name: c for c in spec.conditions}
        sem = asyncio.Semaphore(spec.parallel_runs)
        spent = {"usd": 0.0}
        prog = self.progress[exp_id]

        def tick_done() -> None:
            prog["done_ticks"] += 1

        async def one(run: dict[str, Any]) -> None:
            async with sem:
                if cancel.is_set():
                    run["status"] = "cancelled"
                    return
                preset, cfg = build_run_config(spec, conditions[run["condition"]], run["seed"])
                uses_llm = cfg.llm.provider != "none"
                if uses_llm and spec.maximum_total_spend is not None and spent["usd"] >= spec.maximum_total_spend:
                    run["status"] = "skipped_budget"
                    return
                run["status"] = "running"
                try:
                    if uses_llm:
                        out = await run_with_llm(cfg, self.repo, exp_id, run["condition"], preset, cancel, tick_done)
                    else:
                        out = await asyncio.to_thread(run_rule_based, cfg, self.repo, exp_id, run["condition"],
                                                      preset, cancel, tick_done)
                except RunCancelled:
                    run["status"] = "cancelled"
                    return
                except Exception as exc:
                    log.exception("experiment %s run failed", exp_id)
                    run["status"] = "failed"
                    run["error"] = f"{exc.__class__.__name__}: {exc}"
                    return
                run.update(out, status="completed")
                spent["usd"] += out["summary"].get("llm_spend_usd", 0.0)
                done = sum(1 for r in runs if r["status"] not in ("pending", "running"))
                await asyncio.to_thread(self.repo.update_experiment, exp_id, status="running",
                                        progress=round(done / len(runs), 4))

        await asyncio.to_thread(self.repo.update_experiment, exp_id, status="running", progress=0.0)
        try:
            await asyncio.gather(*(one(r) for r in runs))
        finally:
            names = [c.name for c in spec.conditions]
            results = {
                "runs": runs,
                "comparison": compare(runs, spec.baseline_name, names),
                "series": mean_daily_series(runs, names),
                "total_llm_spend_usd": round(spent["usd"], 6),
            }
            if cancel.is_set():
                status = "cancelled"
            elif any(r["status"] == "failed" for r in runs):
                status = "completed_with_errors"
            else:
                status = "completed"
            failed = [r.get("error") for r in runs if r["status"] == "failed"]
            await asyncio.to_thread(self.repo.update_experiment, exp_id, status=status, progress=1.0,
                                    results=results, error="; ".join(failed[:3]) or None)
            self.cancels.pop(exp_id, None)
            self.progress.pop(exp_id, None)

    # ------------------------------------------------------------------ export
    def export_summary_csv(self, exp: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["experiment_id", "experiment", "condition", "seed", "world_id", "status", *SUMMARY_METRICS])
        for run in (exp.get("results") or {}).get("runs", []):
            summary = run.get("summary", {})
            writer.writerow([exp["id"], exp["name"], run["condition"], run["seed"], run.get("world_id", ""),
                             run["status"], *[summary.get(m, "") for m in SUMMARY_METRICS]])
        return buf.getvalue()

    def export_timeseries_csv(self, exp: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["experiment_id", "condition", "seed", "world_id", *TIMESERIES_KEYS])
        for run in (exp.get("results") or {}).get("runs", []):
            if not run.get("world_id"):
                continue
            for m in self.repo.metrics(run["world_id"]):
                writer.writerow([exp["id"], run["condition"], run["seed"], run["world_id"],
                                 *[m.get(k, "") for k in TIMESERIES_KEYS]])
        return buf.getvalue()

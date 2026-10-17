"""Measure tick cost for growing populations (engine, mock-LLM pipeline, persistence).

    python scripts/stress_test.py --sizes 10 50 100 200 --ticks 48 [--database-url URL]
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import tempfile
import time

from aisim.agents.service import LLMDecider
from aisim.config import load_config
from aisim.engine import Simulation
from aisim.persistence import Database, Repository


def cfg(n: int, provider: str = "none"):
    return load_config("abundance", {
        "simulation": {"population": n, "max_agents": max(n, 20)},
        "world": {"width": 100 + n, "height": 100 + n, "workplace_capacity": max(6, n // 2)},
        "llm": {"provider": provider, "max_queue_size": 1000, "max_concurrent_requests": 50,
                "requests_per_minute": 100000, "maximum_world_spend": None, "maximum_agent_daily_spend": None},
    })


def bench_engine(n: int, ticks: int) -> float:
    sim = Simulation.create(cfg(n), "s")
    times = []
    for _ in range(ticks):
        t0 = time.perf_counter()
        sim.step()
        times.append(time.perf_counter() - t0)
    return statistics.mean(times) * 1000


def bench_mock(n: int, ticks: int) -> float:
    c = cfg(n, "mock")
    sim = Simulation.create(c, "s")
    decider = LLMDecider.from_config(c, "s")

    async def run():
        times = []
        for _ in range(ticks):
            t0 = time.perf_counter()
            reqs = sim.begin_tick()
            props, meta = await decider.decide(sim, reqs)
            sim.apply_decisions(props, meta)
            sim.advance()
            times.append(time.perf_counter() - t0)
        return statistics.mean(times) * 1000

    return asyncio.run(run())


def bench_persist(n: int, ticks: int, url: str, interval: int) -> float:
    db = Database(url)
    db.migrate()
    repo = Repository(db)
    c = cfg(n).model_copy(deep=True)
    c.simulation.snapshot_interval_ticks = interval
    sim = Simulation.create(c, f"stress{n}{interval}{int(time.time() * 1000) % 100000}")
    repo.create_world(sim, "abundance")
    times = []
    for _ in range(ticks):
        r = sim.step()
        t0 = time.perf_counter()
        repo.save_tick(sim, r)
        times.append(time.perf_counter() - t0)
    repo.delete_world(sim.world.id)
    db.dispose()
    return statistics.mean(times) * 1000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[10, 50, 100, 200])
    ap.add_argument("--ticks", type=int, default=48)
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args()
    url = args.database_url or f"sqlite:///{tempfile.mkdtemp()}/stress.db"
    print(f"{'agents':>7} {'engine ms/tick':>15} {'mock-LLM ms/tick':>17} {'save ms (snap/tick)':>20} {'save ms (snap/day)':>19}")
    for n in args.sizes:
        print(f"{n:>7} {bench_engine(n, args.ticks):>15.1f} {bench_mock(n, args.ticks):>17.1f} "
              f"{bench_persist(n, args.ticks, url, 1):>20.1f} {bench_persist(n, args.ticks, url, 24):>19.1f}", flush=True)


if __name__ == "__main__":
    main()

"""Runs one world: tick scheduling, pause/resume/speed, persistence, broadcast.

The simulation clock is decoupled from LLM latency: each tick gives the
decider a bounded decision window, then applies whatever decisions are ready
(the rest receive fallback behaviour). Pausing takes effect between ticks, so
a world is never persisted mid-tick.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..engine.simulation import Simulation, TickResult
from .deciders import Decider
from .hub import Hub
from .views import tick_payload, world_view

log = logging.getLogger(__name__)

MAX_SAVE_ATTEMPTS = 3


class WorldRunner:
    def __init__(self, sim: Simulation, repo, hub: Hub, decider: Decider, preset: str | None = None,
                 status: str = "paused", speed: float = 2.0):
        self.sim = sim
        self.repo = repo
        self.hub = hub
        self.decider = decider
        self.preset = preset
        self.status = status
        self.speed = speed  # ticks per second; 0 = as fast as possible
        self.last_error: str | None = None
        self.last_tick_seconds: float = 0.0
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._unsaved: list[tuple[TickResult, list[dict[str, Any]]]] = []

    @property
    def world_id(self) -> str:
        return self.sim.world.id

    # ------------------------------------------------------------------
    def extra(self) -> dict[str, Any]:
        return {"llm": self.decider.stats(), "last_error": self.last_error,
                "last_tick_seconds": round(self.last_tick_seconds, 3),
                "max_ticks": self.sim.config.simulation.max_ticks}

    def view(self) -> dict[str, Any]:
        return world_view(self.sim, self.status, self.speed, self.extra())

    def _finished(self) -> bool:
        max_ticks = self.sim.config.simulation.max_ticks
        if max_ticks is not None and self.sim.world.tick >= max_ticks:
            return True
        return not self.sim.world.alive_agents()

    async def step(self) -> TickResult:
        async with self._lock:
            if self._finished():
                self.status = "finished"
                raise RuntimeError("world_finished")
            t0 = time.monotonic()
            sim = self.sim
            requests = sim.begin_tick()
            proposals, meta = await self.decider.decide(sim, requests)
            sim.apply_decisions(proposals, meta)
            result = sim.advance()
            stats = self.decider.stats()
            if "spend_usd" in stats:
                result.metrics["llm_spend_usd"] = stats["spend_usd"]
                result.metrics["llm_requests"] = stats.get("requests", 0)
                result.metrics["llm_failures"] = stats.get("failures", 0)
            usage = self.decider.drain_usage()
            if self._finished():
                self.status = "finished"
            self._unsaved.append((result, usage))
            await self._flush(stats.get("spend_usd"))
            self.last_tick_seconds = time.monotonic() - t0
            await self.hub.publish(self.world_id, tick_payload(sim, result, self.status, self.speed, self.extra()))
            return result

    async def _flush(self, spend: float | None) -> None:
        """Persist unsaved ticks in order; tolerate transient database failures."""
        while self._unsaved:
            result, usage = self._unsaved[0]
            last = len(self._unsaved) == 1
            for attempt in range(MAX_SAVE_ATTEMPTS):
                try:
                    await asyncio.to_thread(
                        self.repo.save_tick, self.sim, result, self.status, usage, spend,
                        force_snapshot=last and attempt > 0)
                    break
                except Exception as exc:  # pragma: no cover - exercised in failure tests
                    log.warning("save_tick failed for %s (attempt %d): %s", self.world_id, attempt + 1, exc)
                    self.last_error = f"database: {exc.__class__.__name__}"
                    await asyncio.sleep(0.2 * (attempt + 1))
            else:
                # Keep the tick in memory and pause; the next save retries it.
                self.status = "error"
                return
            self._unsaved.pop(0)
            self.last_error = None if self.last_error and self.last_error.startswith("database") else self.last_error

    async def _loop(self) -> None:
        try:
            while self.status == "running":
                t0 = time.monotonic()
                try:
                    await self.step()
                except RuntimeError as exc:
                    if str(exc) == "world_finished":
                        break
                    raise
                except Exception as exc:
                    log.exception("tick failed for world %s", self.world_id)
                    self.last_error = f"{exc.__class__.__name__}: {exc}"
                    self.status = "error"
                    break
                if self.status != "running":
                    break
                delay = (1.0 / self.speed - (time.monotonic() - t0)) if self.speed > 0 else 0.0
                await asyncio.sleep(max(0.0, delay))
        finally:
            if self.status == "running":
                self.status = "paused"
            await self._persist_status()
            await self.hub.publish(self.world_id, {"type": "status", "world": self.view()})

    async def _persist_status(self) -> None:
        try:
            await asyncio.to_thread(self.repo.set_status, self.world_id, self.status)
        except Exception as exc:  # pragma: no cover
            log.warning("could not persist status for %s: %s", self.world_id, exc)

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            self.status = "running"
            return
        if self._finished():
            self.status = "finished"
            return
        self.status = "running"
        self.last_error = None
        self._task = asyncio.create_task(self._loop(), name=f"world-{self.world_id}")

    async def pause(self) -> None:
        if self.status == "running":
            self.status = "paused"
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=self.sim.config.simulation.decision_timeout_seconds + 10)
            except asyncio.TimeoutError:  # pragma: no cover
                self._task.cancel()
            self._task = None
        await self._persist_status()

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.0, min(float(speed), 100.0))

    async def close(self, remember_running: bool = False) -> None:
        was_running = self.status == "running"
        await self.pause()
        if remember_running and was_running:
            # Shutdown, not a user pause: let auto-resume restart this world.
            self.status = "running"
            await self._persist_status()
            self.status = "paused"
        await self.decider.close()

"""Owns all live worlds and restores them from the database after a restart."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable

from ..config import SimulationConfig, load_config
from ..engine.simulation import Simulation
from ..persistence.repository import Repository
from .deciders import Decider, RuleDecider
from .hub import Hub
from .runner import WorldRunner

log = logging.getLogger(__name__)

DeciderFactory = Callable[[SimulationConfig, str], Decider]


def default_decider_factory(config: SimulationConfig, world_id: str) -> Decider:
    if config.llm.provider == "none":
        return RuleDecider()
    from ..agents.service import LLMDecider

    return LLMDecider.from_config(config, world_id)


class WorldManager:
    def __init__(self, repo: Repository, hub: Hub, decider_factory: DeciderFactory | None = None,
                 auto_resume: bool = False):
        self.repo = repo
        self.hub = hub
        self.decider_factory = decider_factory or default_decider_factory
        self.auto_resume = auto_resume
        self.runners: dict[str, WorldRunner] = {}
        self._lock = asyncio.Lock()

    async def create_world(self, preset: str = "default", overrides: dict[str, Any] | None = None,
                           name: str | None = None, start: bool = False) -> WorldRunner:
        config = load_config(preset, overrides)
        if name:
            config = config.model_copy(update={"name": name})
        if config.simulation.population > config.simulation.max_agents:
            raise ValueError("population exceeds max_agents")
        sim = Simulation.create(config, uuid.uuid4().hex[:12])
        await asyncio.to_thread(self.repo.create_world, sim, preset)
        runner = WorldRunner(sim, self.repo, self.hub, self.decider_factory(config, sim.world.id), preset)
        self.runners[sim.world.id] = runner
        if start:
            runner.start()
        return runner

    async def load(self, world_id: str) -> WorldRunner | None:
        async with self._lock:
            if world_id in self.runners:
                return self.runners[world_id]
            row = await asyncio.to_thread(self.repo.get_world, world_id)
            if row is None or row.snapshot is None:
                return None
            config = SimulationConfig.model_validate(row.config)
            sim = Simulation.from_snapshot(config, row.snapshot)
            if row.tick > row.snapshot_tick:
                # Records written after the last snapshot would be duplicated on replay.
                await asyncio.to_thread(self.repo.truncate_after, world_id, row.snapshot_tick)
            status = row.status if row.status in ("finished",) else "paused"
            runner = WorldRunner(sim, self.repo, self.hub, self.decider_factory(config, world_id), row.preset,
                                 status=status)
            self.runners[world_id] = runner
            if self.auto_resume and row.status == "running":
                runner.start()
            return runner

    async def load_all(self) -> int:
        worlds = await asyncio.to_thread(self.repo.list_worlds)
        n = 0
        for w in worlds:
            try:
                if await self.load(w["id"]) is not None:
                    n += 1
            except Exception:  # pragma: no cover - a corrupt world must not block startup
                log.exception("failed to restore world %s", w["id"])
        return n

    async def get(self, world_id: str) -> WorldRunner | None:
        return self.runners.get(world_id) or await self.load(world_id)

    async def delete(self, world_id: str) -> bool:
        runner = self.runners.pop(world_id, None)
        if runner is not None:
            await runner.close()
        row = await asyncio.to_thread(self.repo.get_world, world_id)
        if row is None and runner is None:
            return False
        await asyncio.to_thread(self.repo.delete_world, world_id)
        return True

    async def shutdown(self) -> None:
        await asyncio.gather(*(r.close(remember_running=True) for r in self.runners.values()),
                             return_exceptions=True)

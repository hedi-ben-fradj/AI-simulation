"""Writes the daily chronicle of a world.

After the last tick of each day is saved, the chronicler gathers the day's
records, builds a digest (``analysis/chronicle.py``) together with every
agent's state at nightfall, and stores a storyline written by the built-in
template right away. If the world's narrator is an LLM, it then asks the
world's model to write a richer storyline from the same digest and replaces the
template version. All of this runs in the background: ticks never wait for it.

LLM narration counts toward the world's spend like any other request and is
logged in ``llm_usage`` under the agent id ``chronicler``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..analysis.chronicle import (
    NARRATIVE_SCHEMA, build_digest, narrator_request, parse_narrative, template_story,
)
from ..engine.simulation import Simulation
from ..llm.base import LLMError, LLMRequest
from .appearance import agent_sprite
from .views import message_status

log = logging.getLogger(__name__)

LLM_NARRATORS = ("anthropic", "openrouter", "claude_code")
CHRONICLER_ID = "chronicler"


def agent_state(sim: Simulation, a) -> dict[str, Any]:
    return {
        "id": a.id, "name": a.name, "alive": a.alive, "controller": a.controller,
        "health": round(a.health, 1), "hunger": round(a.hunger, 1), "energy": round(a.energy, 1),
        "tokens": round(a.tokens, 2), "food": a.food, "mood": a.current_mood if a.alive else "dead",
        "action": a.current_action if a.alive else "dead",
        "sprite": agent_sprite(a.id, a.initial_personality or a.personality),
    }


class Chronicler:
    def __init__(self, runner):
        self.runner = runner
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._morning: dict[str, Any] = {}
        self._morning_day = -1
        self._capture_morning()

    # ------------------------------------------------------------ helpers
    @property
    def sim(self) -> Simulation:
        return self.runner.sim

    @property
    def tpd(self) -> int:
        return self.sim.config.simulation.ticks_per_day

    def narrator_provider(self):
        """The provider that writes LLM storylines for this world, or None (template only)."""
        cfg = self.sim.config.chronicle
        provider = getattr(self.runner.decider, "provider", None)
        if cfg.narrator == "template" or provider is None or provider.name not in LLM_NARRATORS:
            return None
        if getattr(self.runner.decider, "credential", None) == "missing":
            return None
        return provider

    def _capture_morning(self) -> None:
        sim = self.sim
        self._morning_day = sim.world.tick // self.tpd + 1 if sim.world.tick % self.tpd == 0 else -1
        self._morning = {a.id: {**agent_state(sim, a), "alloc": dict(a.time_allocation),
                                "known": set(a.relationships)} for a in sim.world.agents.values()}

    def _nightfall(self, day: int) -> list[dict[str, Any]]:
        sim = self.sim
        hours = 24 / self.tpd
        out = []
        for a in sim.world.agents.values():
            state = agent_state(sim, a)
            morning = self._morning.get(a.id) if self._morning_day == day else None
            if morning:
                state["morning"] = {k: morning[k] for k in ("health", "hunger", "tokens")}
                alloc = morning["alloc"]
                spent = {k: (v - alloc.get(k, 0)) * hours for k, v in a.time_allocation.items()}
                state["hours"] = {k: round(v, 1) for k, v in sorted(spent.items(), key=lambda kv: -kv[1]) if v > 0}
                state["met_today"] = [r.other_name for oid, r in a.relationships.items() if oid not in morning["known"]]
            out.append(state)
        return out

    def _digest(self, day: int, records: dict[str, Any], agents: list[dict[str, Any]] | None,
                complete: bool) -> dict[str, Any]:
        sim = self.sim
        names = {a.id: a.name for a in sim.world.agents.values()}
        messages = [{**m, "status": message_status(sim, m)} for m in records["messages"]]
        t0 = (day - 1) * self.tpd
        return build_digest(
            day=day, from_tick=t0, to_tick=t0 + self.tpd, ticks_per_day=self.tpd, names=names,
            events=records["events"], messages=messages, decisions=records["decisions"],
            memories=records["memories"], trust_changes=records["trust_changes"],
            trait_changes=records["trait_changes"], metrics=records["metrics"], agents=agents, complete=complete)

    async def _publish(self, day: int, headline: str, narrator: str) -> None:
        await self.runner.hub.publish(self.runner.world_id, {"type": "chronicle", "day": day,
                                                             "headline": headline, "narrator": narrator})

    # ------------------------------------------------------------ the day ends
    def on_tick(self) -> None:
        """Call after a tick is saved; schedules the chronicle when a day has just ended."""
        if not self.sim.config.chronicle.enabled:
            return
        tick = self.sim.world.tick
        if tick == 0 or tick % self.tpd:
            return
        day = tick // self.tpd
        nightfall = self._nightfall(day)
        self._capture_morning()
        task = asyncio.create_task(self.write_day(day, nightfall), name=f"chronicle-{self.runner.world_id}-{day}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def write_day(self, day: int, nightfall: list[dict[str, Any]] | None) -> None:
        wid = self.runner.world_id
        t0 = (day - 1) * self.tpd
        try:
            async with self._lock:
                records = await asyncio.to_thread(self.runner.repo.day_records, wid, t0, t0 + self.tpd)
                digest = self._digest(day, records, nightfall, complete=True)
                headline, story = template_story(digest)
                await asyncio.to_thread(self.runner.repo.save_day_summary, wid, day, t0, t0 + self.tpd,
                                        headline, story, digest)
                await self._publish(day, headline, "template")
            if self.narrator_provider() is not None:
                await self.narrate(day)
        except asyncio.CancelledError:
            raise
        except Exception:  # the chronicle must never break the world
            log.exception("could not write the chronicle of day %d for world %s", day, wid)

    async def narrate(self, day: int) -> dict[str, Any]:
        """(Re)write a stored day's storyline with the world's LLM. Raises LookupError / RuntimeError."""
        provider = self.narrator_provider()
        if provider is None:
            raise RuntimeError("this world has no LLM narrator (rule-based or mock agents, or no API key)")
        decider = self.runner.decider
        cap = self.sim.config.llm.maximum_world_spend
        if cap is not None and getattr(decider, "spend_usd", 0.0) >= cap:
            raise RuntimeError("the world's LLM spend cap is reached")
        wid = self.runner.world_id
        async with self._lock:
            stored = await asyncio.to_thread(self.runner.repo.day_summary, wid, day)
            if stored is None:
                raise LookupError(f"day {day} has no chronicle yet")
            previous = [d for d in await asyncio.to_thread(self.runner.repo.day_summaries, wid) if d["day"] < day]
            system, user = narrator_request(stored["digest"], previous)
            request = LLMRequest(system=system, user=user, json_schema=NARRATIVE_SCHEMA,
                                 max_output_tokens=self.sim.config.chronicle.max_output_tokens,
                                 metadata={"agent_id": CHRONICLER_ID, "tick": stored["to_tick"] - 1})
            timeout = max(60.0, self.sim.config.simulation.decision_timeout_seconds * 2)
            try:
                response = await asyncio.wait_for(provider.complete(request), timeout=timeout)
                headline, story, notable = parse_narrative(response.text)
            except asyncio.TimeoutError as exc:
                self._record(stored, None, "timeout")
                raise RuntimeError("the narrator did not answer in time") from exc
            except LLMError as exc:
                self._record(stored, exc.response, exc.kind)
                raise RuntimeError(f"the narrator failed: {exc.kind}") from exc
            except (ValueError, KeyError) as exc:
                self._record(stored, response, "invalid_output")
                raise RuntimeError("the narrator's answer could not be read") from exc
            self._record(stored, response, None)
            await asyncio.to_thread(self.runner.repo.save_day_summary, wid, day, stored["from_tick"],
                                    stored["to_tick"], headline, story, stored["digest"], "llm", provider.model,
                                    notable)
            await self._publish(day, headline, "llm")
            return await asyncio.to_thread(self.runner.repo.day_summary, wid, day)

    def _record(self, stored: dict[str, Any], response, error: str | None) -> None:
        record = getattr(self.runner.decider, "_record", None)
        if record is not None:  # counts toward spend and lands in llm_usage with the next tick
            record(CHRONICLER_ID, stored["to_tick"] - 1, response, error is None, error)

    # ------------------------------------------------------------ reading
    def backfill(self) -> int:
        """Write template chronicles for finished days that have none (e.g. older worlds). Sync."""
        if not self.sim.config.chronicle.enabled:
            return 0
        wid = self.runner.world_id
        repo = self.runner.repo
        done = {d["day"] for d in repo.day_summaries(wid)}
        finished = self.sim.world.tick // self.tpd
        written = 0
        for day in range(1, finished + 1):
            if day in done:
                continue
            t0 = (day - 1) * self.tpd
            digest = self._digest(day, repo.day_records(wid, t0, t0 + self.tpd), None, complete=True)
            headline, story = template_story(digest)
            # Never replaces a storyline written meanwhile by the end-of-day task.
            if repo.save_day_summary(wid, day, t0, t0 + self.tpd, headline, story, digest, only_if_missing=True):
                written += 1
        return written

    def today(self) -> dict[str, Any] | None:
        """The day in progress so far (not stored). Sync."""
        tick = self.sim.world.tick
        if tick % self.tpd == 0:
            return None
        day = tick // self.tpd + 1
        t0 = (day - 1) * self.tpd
        records = self.runner.repo.day_records(self.runner.world_id, t0, tick)
        digest = self._digest(day, records, self._nightfall(day), complete=False)
        headline, story = template_story(digest)
        return {"day": day, "from_tick": t0, "to_tick": tick, "headline": headline, "story": story,
                "notable": [], "narrator": "template", "model": None, "in_progress": True,
                "stats": digest["stats"], "economy": digest["economy"], "highlights": digest["highlights"][:8],
                "digest": digest}

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

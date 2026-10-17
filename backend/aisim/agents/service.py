"""Agent decision service: turns decision requests into proposals via an LLM.

Per tick (the "controlled tick barrier", spec 5.3):

1. Rule-controlled agents are decided immediately by the rule policy.
2. LLM agents are checked against spend caps and the per-tick queue limit
   (backpressure); those over a limit get the rule-based fallback.
3. Contexts are built synchronously from the current state (a snapshot of
   what each agent knows), then requests run concurrently, limited by a
   semaphore and a token-bucket rate limiter.
4. After ``decision_timeout_seconds`` pending requests are cancelled and those
   agents receive the fallback (or idle when ``fallback_on_timeout`` is off).
5. Responses are parsed and schema-validated; the engine validates the
   resulting proposals against world rules afterwards.

Nothing here mutates world state. Usage, latency, cost and failures of every
request are recorded for persistence.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

from ..config import SimulationConfig
from ..engine.actions import ActionProposal
from ..engine.policy import decide as rule_decide
from ..engine.simulation import DecisionRequest, Simulation
from ..llm import LLMError, LLMProvider, LLMRequest, LLMResponse, make_provider
from ..llm.pricing import estimate_cost, prices_for
from ..llm.ratelimit import RateLimiter
from .context import build_context
from .prompt import build_system_prompt
from .schema import InvalidOutput, decision_json_schema, parse_decision

log = logging.getLogger(__name__)


class LLMDecider:
    def __init__(self, config: SimulationConfig, provider: LLMProvider, world_id: str = ""):
        self.config = config
        self.cfg = config.llm
        self.provider = provider
        self.world_id = world_id
        self.system_prompt = build_system_prompt(config)
        self.schema = decision_json_schema()
        self.semaphore = asyncio.Semaphore(max(1, self.cfg.max_concurrent_requests))
        # The offline mock makes no real API calls, so it is not rate-limited.
        self.limiter = RateLimiter(self.cfg.requests_per_minute) if provider.name != "mock" else None
        self.rate_limited = 0
        self.input_price, self.output_price = prices_for(
            provider.model, self.cfg.input_price_per_mtok, self.cfg.output_price_per_mtok)
        if provider.name == "mock" and self.cfg.input_price_per_mtok is None:
            self.input_price = self.output_price = 0.0  # offline: no real spend
        self.spend_usd = 0.0
        self.agent_day_spend: dict[tuple[int, str], float] = defaultdict(float)
        self.requests = 0
        self.failures = 0
        self.timeouts = 0
        self.fallbacks = 0
        self.in_flight = 0
        self.budget_exhausted = False
        self.last_context_tokens = 0
        self._usage: list[dict[str, Any]] = []

    @classmethod
    def from_config(cls, config: SimulationConfig, world_id: str = "") -> "LLMDecider":
        return cls(config, make_provider(config.llm), world_id)

    # ------------------------------------------------------------------ public
    def restore_spend(self, spend_usd: float) -> None:
        self.spend_usd = spend_usd or 0.0

    def drain_usage(self) -> list[dict[str, Any]]:
        out, self._usage = self._usage, []
        return out

    def stats(self) -> dict[str, Any]:
        return {
            "provider": self.provider.name, "model": self.provider.model, "requests": self.requests,
            "failures": self.failures, "timeouts": self.timeouts, "fallbacks": self.fallbacks,
            "spend_usd": round(self.spend_usd, 6), "max_world_spend": self.cfg.maximum_world_spend,
            "max_agent_daily_spend": self.cfg.maximum_agent_daily_spend, "budget_exhausted": self.budget_exhausted,
            "queue_depth": self.in_flight, "effort": self.cfg.effort, "rate_limited": self.rate_limited,
            "last_context_tokens": self.last_context_tokens,
        }

    async def close(self) -> None:
        await self.provider.close()

    async def decide(self, sim: Simulation, requests: list[DecisionRequest]
                     ) -> tuple[dict[str, ActionProposal], dict[str, dict[str, Any]]]:
        proposals: dict[str, ActionProposal] = {}
        meta: dict[str, dict[str, Any]] = {}
        llm_requests: list[DecisionRequest] = []
        for req in requests:
            if req.controller != "llm":
                proposals[req.agent_id] = rule_decide(sim, req)
                continue
            blocked = self._budget_block(sim, req.agent_id)
            if blocked:
                meta[req.agent_id] = {"fallback_reason": blocked}
                self.fallbacks += 1
                continue
            llm_requests.append(req)

        # Backpressure: bound the number of LLM calls per tick.
        if len(llm_requests) > self.cfg.max_queue_size:
            for req in llm_requests[self.cfg.max_queue_size:]:
                meta[req.agent_id] = {"fallback_reason": "backpressure"}
                self.fallbacks += 1
            llm_requests = llm_requests[: self.cfg.max_queue_size]
        if not llm_requests:
            return proposals, meta

        tick = sim.world.tick
        jobs: dict[str, asyncio.Task] = {}
        for req in llm_requests:
            ctx = build_context(sim, req)
            self.last_context_tokens = ctx.tokens
            metadata: dict[str, Any] = {"agent_id": req.agent_id, "tick": tick}
            if self.provider.name == "mock":
                metadata["hint"] = rule_decide(sim, req).model_dump(exclude_none=True)
            request = LLMRequest(system=self.system_prompt, user=ctx.text, json_schema=self.schema,
                                 max_output_tokens=self.cfg.max_output_tokens, metadata=metadata)
            jobs[req.agent_id] = asyncio.create_task(self._call(req.agent_id, tick, request))

        done, pending = await asyncio.wait(jobs.values(), timeout=self.config.simulation.decision_timeout_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        for agent_id, task in jobs.items():
            if task in pending:
                self.timeouts += 1
                self.failures += 1
                self._record(agent_id, tick, None, False, "decision_timeout")
                if self.config.simulation.fallback_on_timeout:
                    meta[agent_id] = {"fallback_reason": "timeout"}
                    self.fallbacks += 1
                else:
                    proposals[agent_id] = ActionProposal(action="idle", source="llm",
                                                         visible_intention="(no decision in time)")
                continue
            proposal, info = task.result()
            if proposal is not None:
                proposals[agent_id] = proposal
                meta[agent_id] = info
            else:
                self.fallbacks += 1
                meta[agent_id] = info
        return proposals, meta

    # ---------------------------------------------------------------- internals
    def _budget_block(self, sim: Simulation, agent_id: str) -> str | None:
        cap = self.cfg.maximum_world_spend
        if cap is not None and self.spend_usd >= cap:
            self.budget_exhausted = True
            return "world_budget_exhausted"
        daily = self.cfg.maximum_agent_daily_spend
        if daily is not None and self.agent_day_spend[(sim.day, agent_id)] >= daily:
            return "agent_daily_budget_exhausted"
        return None

    async def _call(self, agent_id: str, tick: int, request: LLMRequest
                    ) -> tuple[ActionProposal | None, dict[str, Any]]:
        async with self.semaphore:
            if self.limiter is not None and not self.limiter.try_acquire():
                # Waiting longer than half the decision window would stall the whole
                # tick; fall back now instead and let the slot refill.
                if self.limiter.wait_time() > self.config.simulation.decision_timeout_seconds / 2:
                    self.rate_limited += 1
                    return None, {"fallback_reason": "rate_limited"}
                await self.limiter.acquire()
            self.in_flight += 1
            self.requests += 1
            t0 = time.monotonic()
            try:
                response = await self.provider.complete(request)
            except LLMError as exc:
                self.failures += 1
                self._record(agent_id, tick, exc.response, False, exc.kind)
                if exc.kind in ("authentication", "permission_denied", "model_not_found"):
                    log.error("LLM configuration error for world %s: %s", self.world_id, exc)
                return None, {"fallback_reason": f"llm_error:{exc.kind}",
                              "latency_ms": (time.monotonic() - t0) * 1000}
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # defensive: provider bugs must not break the tick
                self.failures += 1
                log.exception("unexpected provider error")
                self._record(agent_id, tick, None, False, f"unexpected:{exc.__class__.__name__}")
                return None, {"fallback_reason": "llm_error:unexpected"}
            finally:
                self.in_flight -= 1
        latency = (time.monotonic() - t0) * 1000
        try:
            decision = parse_decision(response.text)
        except InvalidOutput as exc:
            self.failures += 1
            self._record(agent_id, tick, response, False, f"invalid_output: {exc}")
            return None, {"fallback_reason": "invalid_output", "latency_ms": latency}
        self._record(agent_id, tick, response, True, None)
        return decision.to_proposal(), {"latency_ms": latency}

    def _record(self, agent_id: str, tick: int, response: LLMResponse | None, success: bool,
                error: str | None) -> None:
        cost = 0.0
        if response is not None:
            cost = estimate_cost(self.input_price, self.output_price, response.input_tokens,
                                 response.output_tokens, response.cache_read_tokens, response.cache_write_tokens)
        self.spend_usd += cost
        day = tick // self.config.simulation.ticks_per_day
        self.agent_day_spend[(day, agent_id)] += cost
        self._usage.append({
            "agent_id": agent_id, "tick": tick, "provider": self.provider.name, "model": self.provider.model,
            "input_tokens": (response.input_tokens + response.cache_read_tokens + response.cache_write_tokens)
            if response else 0,
            "output_tokens": response.output_tokens if response else 0,
            "cost_usd": round(cost, 8), "latency_ms": round(response.latency_ms, 2) if response else 0.0,
            "success": success, "error": error, "attempts": 1,
        })

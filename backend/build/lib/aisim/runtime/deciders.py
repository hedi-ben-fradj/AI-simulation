"""Decision providers used by the runtime.

A decider turns the engine's decision requests into proposals. The engine
never calls a decider itself; the runtime does, between ``begin_tick`` and
``apply_decisions``, so the simulation core stays independent of any LLM.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..engine.actions import ActionProposal
from ..engine.policy import decide as rule_decide
from ..engine.simulation import DecisionRequest, Simulation


class Decider(Protocol):
    async def decide(self, sim: Simulation, requests: list[DecisionRequest]
                     ) -> tuple[dict[str, ActionProposal], dict[str, dict[str, Any]]]: ...

    def drain_usage(self) -> list[dict[str, Any]]: ...

    def stats(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class RuleDecider:
    """All agents use the deterministic rule-based policy."""

    async def decide(self, sim, requests):
        return {r.agent_id: rule_decide(sim, r) for r in requests}, {}

    def drain_usage(self):
        return []

    def stats(self):
        return {"provider": "none"}

    async def close(self):
        return None

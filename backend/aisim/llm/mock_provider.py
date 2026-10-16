"""Offline mock provider.

Exercises the full LLM pipeline (prompting, budgets, concurrency, parsing,
validation) without network or cost. It answers with the rule-based policy's
choice (passed in ``request.metadata["hint"]``), and can inject latency,
failures and malformed output from a seeded random stream.
"""

from __future__ import annotations

import asyncio
import json
import random

from .base import LLMError, LLMRequest, LLMResponse
from ..engine.communication import estimate_tokens


class MockProvider:
    name = "mock"

    def __init__(self, model: str = "mock-model", latency_seconds: float = 0.0, failure_rate: float = 0.0,
                 invalid_output_rate: float = 0.0, seed: int = 0):
        self.model = model
        self.latency_seconds = latency_seconds
        self.failure_rate = failure_rate
        self.invalid_output_rate = invalid_output_rate
        self.rng = random.Random(seed)
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        latency = request.metadata.get("mock_latency", self.latency_seconds)
        if latency:
            await asyncio.sleep(latency)
        if self.rng.random() < self.failure_rate:
            raise LLMError("server_error", "injected failure", retryable=True)
        hint = dict(request.metadata.get("hint") or {"action": "idle"})
        hint.setdefault("visible_intention", "Following my usual routine.")
        if self.rng.random() < self.invalid_output_rate:
            text = '{"action": "work", "duration": '  # truncated JSON
        else:
            text = json.dumps({
                "action": hint.get("action"),
                "target": hint.get("target"),
                "duration": hint.get("duration"),
                "quantity": hint.get("quantity"),
                "resource_offer": hint.get("resource_offer"),
                "resource_request": hint.get("resource_request"),
                "message": hint.get("message"),
                "message_to": hint.get("message_to"),
                "visible_intention": hint.get("visible_intention"),
                "memory_candidates": [],
                "belief": None,
                "confidence": 0.5,
            })
        return LLMResponse(
            text=text, model=self.model, input_tokens=estimate_tokens(request.system + request.user),
            output_tokens=estimate_tokens(text), latency_ms=latency * 1000, stop_reason="end_turn",
        )

    async def close(self) -> None:
        return None

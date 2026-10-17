"""Async token-bucket rate limiter for outbound LLM requests."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    def __init__(self, per_minute: int):
        self.capacity = max(1, per_minute)
        self.tokens = float(self.capacity)
        self.rate = self.capacity / 60.0
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    def try_acquire(self) -> bool:
        self._refill()
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                self._refill()
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)

"""WebSocket fan-out of live world updates."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

log = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self._subs: dict[str, set[Any]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, world_id: str, ws: Any) -> None:
        async with self._lock:
            self._subs[world_id].add(ws)

    async def unsubscribe(self, world_id: str, ws: Any) -> None:
        async with self._lock:
            self._subs[world_id].discard(ws)

    def subscribers(self, world_id: str) -> int:
        return len(self._subs.get(world_id, ()))

    async def publish(self, world_id: str, payload: dict[str, Any]) -> None:
        subs = list(self._subs.get(world_id, ()))
        if not subs:
            return
        text = json.dumps(payload, default=str)

        async def send(ws):
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=2.0)
            except Exception:  # slow or closed client: drop it rather than block the world
                await self.unsubscribe(world_id, ws)

        await asyncio.gather(*(send(ws) for ws in subs))

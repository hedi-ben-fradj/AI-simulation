"""Seeded, named random streams.

Each random process (initialisation, policy choices, existential activation,
environment, ...) draws from its own stream so that adding draws to one
process does not shift the sequence of another. Stream state is serialisable
so a restored world continues the exact same sequence.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any


def _derive_seed(seed: int, name: str) -> int:
    digest = hashlib.sha256(f"{seed}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


class RandomStreams:
    def __init__(self, seed: int):
        self.seed = seed
        self._streams: dict[str, random.Random] = {}

    def get(self, name: str) -> random.Random:
        stream = self._streams.get(name)
        if stream is None:
            stream = random.Random(_derive_seed(self.seed, name))
            self._streams[name] = stream
        return stream

    def __getitem__(self, name: str) -> random.Random:
        return self.get(name)

    def to_state(self) -> dict[str, Any]:
        out: dict[str, Any] = {"seed": self.seed, "streams": {}}
        for name, stream in self._streams.items():
            version, internal, gauss = stream.getstate()
            out["streams"][name] = [version, list(internal), gauss]
        return out

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "RandomStreams":
        obj = cls(int(state["seed"]))
        for name, (version, internal, gauss) in state.get("streams", {}).items():
            stream = random.Random()
            stream.setstate((version, tuple(internal), gauss))
            obj._streams[name] = stream
        return obj

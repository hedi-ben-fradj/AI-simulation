"""Provider-neutral request/response types.

A new model provider only needs to implement :class:`LLMProvider.complete`;
nothing in the engine or the decision service is provider-specific.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMRequest:
    system: str
    user: str
    json_schema: dict[str, Any]
    max_output_tokens: int
    # Free-form data for providers that need it (e.g. the mock's rule-based hint).
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: float = 0.0
    stop_reason: str | None = None
    served_by: str | None = None


class LLMError(Exception):
    """A failed request. ``kind`` is a short machine-readable category."""

    def __init__(self, kind: str, message: str = "", retryable: bool = False,
                 response: LLMResponse | None = None):
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind = kind
        self.retryable = retryable
        # Usage of a request that completed but was unusable (e.g. refusal).
        self.response = response


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    async def close(self) -> None: ...

"""OpenRouter provider (OpenAI-compatible chat completions over HTTPS).

* One API key reaches many models (Anthropic, Google, OpenAI, …); model IDs
  look like ``google/gemini-2.5-flash`` or ``anthropic/claude-haiku-4.5``.
* Structured output: the decision schema is sent as ``response_format``
  (``json_schema``, strict) and ``provider.require_parameters`` routes only to
  upstream providers that honour it.
* Cost: ``usage.include`` makes OpenRouter report the exact charge for each
  request, which is what spend caps count.
* Anthropic models get an explicit prompt-cache breakpoint on the shared system
  prompt; other providers cache automatically where they support it.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from .base import LLMError, LLMRequest, LLMResponse

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# Reasoning tokens count toward max_tokens on OpenRouter; leave room for the answer.
REASONING_HEADROOM_TOKENS = 2000

_STATUS_KINDS = {
    400: "bad_request", 401: "authentication", 402: "insufficient_credits", 403: "permission_denied",
    404: "model_not_found", 408: "timeout", 429: "rate_limited",
}


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, model: str, api_key: str | None, timeout_seconds: float = 30.0, max_retries: int = 1,
                 effort: str | None = "low", prompt_caching: bool = True, base_url: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.model = model
        self.api_key = api_key
        self.effort = effort
        self.prompt_caching = prompt_caching
        self.max_retries = max(0, max_retries)
        self.base_url = (base_url or os.environ.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    def _body(self, request: LLMRequest) -> dict[str, Any]:
        if self.prompt_caching and self.model.startswith("anthropic/"):
            system: Any = [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}]
        else:
            system = request.system
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": request.user}],
            "max_tokens": request.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "agent_decision", "strict": True, "schema": request.json_schema},
            },
            "provider": {"require_parameters": True},
            "usage": {"include": True},
        }
        if self.effort:
            body["reasoning"] = {"effort": self.effort, "exclude": True}
            body["max_tokens"] = request.max_output_tokens + REASONING_HEADROOM_TOKENS
        return body

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise LLMError("missing_api_key", "no OpenRouter API key for this world or server")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Title": "AI Agent Civilization Simulation",
        }
        body = self._body(request)
        t0 = time.monotonic()
        attempt = 0
        while True:
            try:
                return await self._once(headers, body, t0)
            except LLMError as exc:
                if not exc.retryable or attempt >= self.max_retries:
                    raise
            attempt += 1
            await asyncio.sleep(0.5 * attempt)

    async def _once(self, headers: dict[str, str], body: dict[str, Any], t0: float) -> LLMResponse:
        try:
            res = await self.client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMError("timeout", "request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError("network", str(exc)[:200], retryable=True) from exc
        try:
            data = res.json()
        except ValueError:
            data = {}
        if res.status_code != 200 or "error" in data:
            err = data.get("error") or {}
            code = err.get("code") if isinstance(err.get("code"), int) else res.status_code
            if code == 200:  # error reported inside a 200 response (upstream failure)
                code = 502
            kind = _STATUS_KINDS.get(code, "server_error" if code >= 500 else f"http_{code}")
            raise LLMError(kind, str(err.get("message") or res.text)[:200],
                           retryable=code >= 500 or code in (408, 429))

        usage = data.get("usage") or {}
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        response = LLMResponse(
            text="",
            model=self.model,
            input_tokens=max(0, (usage.get("prompt_tokens") or 0) - cached),
            output_tokens=usage.get("completion_tokens") or 0,
            cache_read_tokens=cached,
            latency_ms=(time.monotonic() - t0) * 1000,
            stop_reason=choice.get("finish_reason"),
            served_by=data.get("model") or self.model,
            cost_usd=float(usage["cost"]) if usage.get("cost") is not None else None,
        )
        if message.get("refusal"):
            raise LLMError("refusal", str(message["refusal"])[:200], response=response)
        if choice.get("finish_reason") == "length":
            raise LLMError("max_tokens", "output truncated", response=response)
        content = message.get("content")
        if isinstance(content, list):  # some upstreams return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        response.text = content or ""
        if not response.text:
            raise LLMError("empty_response", str(choice.get("finish_reason")), response=response)
        return response

    async def close(self) -> None:
        await self.client.aclose()

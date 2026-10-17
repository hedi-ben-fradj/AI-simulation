"""Anthropic Claude provider (official async SDK).

* Structured output: the decision JSON schema is passed as
  ``output_config.format`` so the response is schema-valid JSON.
* The static part of the prompt (world rules, output contract) is the system
  prompt and is marked for prompt caching; it is identical for every agent
  and tick, so it is cached across the whole world.
* Policy declines (``stop_reason == "refusal"``) are retried server-side on
  Anthropic's recommended fallback model when the model supports it.
* The API key is read from the environment by the SDK and never leaves the
  backend.
"""

from __future__ import annotations

import os
import time
from typing import Any

import anthropic

from .base import LLMError, LLMRequest, LLMResponse

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models without server-side fallback support (sending `fallbacks` is pointless or rejected).
_NO_FALLBACK_PREFIXES = ("claude-haiku",)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, timeout_seconds: float = 30.0, max_retries: int = 1,
                 effort: str | None = "low", server_side_fallback: bool = True, prompt_caching: bool = True,
                 api_key: str | None = None):
        self.model = model
        self.effort = effort
        self.server_side_fallback = server_side_fallback and not model.startswith(_NO_FALLBACK_PREFIXES)
        self.prompt_caching = prompt_caching
        kwargs: dict[str, Any] = {"timeout": timeout_seconds, "max_retries": max_retries}
        if api_key:
            kwargs["api_key"] = api_key
        self.has_key = bool(api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.client = anthropic.AsyncAnthropic(**kwargs)

    def _params(self, request: LLMRequest) -> dict[str, Any]:
        system_block: dict[str, Any] = {"type": "text", "text": request.system}
        if self.prompt_caching:
            system_block["cache_control"] = {"type": "ephemeral"}
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": request.json_schema}}
        if self.effort:
            output_config["effort"] = self.effort
        return {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "system": [system_block],
            "messages": [{"role": "user", "content": request.user}],
            "output_config": output_config,
        }

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.has_key:
            raise LLMError("missing_api_key", "no Anthropic API key for this world or server")
        params = self._params(request)
        t0 = time.monotonic()
        try:
            if self.server_side_fallback:
                message = await self.client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], fallbacks="default")
            else:
                message = await self.client.messages.create(**params)
        except anthropic.AuthenticationError as exc:
            raise LLMError("authentication", str(exc.message)) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("permission_denied", str(exc.message)) from exc
        except anthropic.NotFoundError as exc:
            raise LLMError("model_not_found", str(exc.message)) from exc
        except anthropic.BadRequestError as exc:
            raise LLMError("bad_request", str(exc.message)[:200]) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("rate_limited", str(exc.message)[:200], retryable=True) from exc
        except anthropic.APITimeoutError as exc:
            raise LLMError("timeout", "request timed out", retryable=True) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("network", str(exc)[:200], retryable=True) from exc
        except anthropic.APIStatusError as exc:
            kind = "server_error" if exc.status_code >= 500 else f"http_{exc.status_code}"
            raise LLMError(kind, str(exc.message)[:200], retryable=exc.status_code >= 500) from exc
        latency = (time.monotonic() - t0) * 1000

        usage = message.usage
        response = LLMResponse(
            text="",
            model=self.model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            latency_ms=latency,
            stop_reason=message.stop_reason,
            served_by=getattr(message, "model", None),
        )
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMError("refusal", str(category or ""), response=response)
        if message.stop_reason == "max_tokens":
            raise LLMError("max_tokens", "output truncated", response=response)
        response.text = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
        if not response.text:
            raise LLMError("empty_response", str(message.stop_reason), response=response)
        return response

    async def close(self) -> None:
        await self.client.close()

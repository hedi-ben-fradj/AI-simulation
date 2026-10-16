"""Build the configured provider."""

from __future__ import annotations

from ..config.schema import LLMSection
from .base import LLMProvider


def make_provider(cfg: LLMSection) -> LLMProvider:
    if cfg.provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            model=cfg.model, timeout_seconds=cfg.request_timeout_seconds, max_retries=cfg.max_retries,
            effort=cfg.effort, server_side_fallback=cfg.server_side_fallback, prompt_caching=cfg.prompt_caching,
        )
    if cfg.provider == "mock":
        from .mock_provider import MockProvider

        return MockProvider(latency_seconds=cfg.mock_latency_seconds, failure_rate=cfg.mock_failure_rate,
                            invalid_output_rate=cfg.mock_invalid_output_rate, seed=cfg.mock_seed)
    raise ValueError(f"no LLM provider for '{cfg.provider}'")

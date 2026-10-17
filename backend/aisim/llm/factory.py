"""Build the configured provider."""

from __future__ import annotations

from ..config.schema import LLMSection
from . import credentials
from .base import LLMProvider

# Used when an OpenRouter world has a model ID without a vendor prefix (e.g. the
# Anthropic-style default "claude-opus-5-5").
OPENROUTER_DEFAULT_MODEL = "google/gemini-2.5-flash"
CLAUDE_CODE_DEFAULT_MODEL = "sonnet"


def make_provider(cfg: LLMSection, world_id: str = "", decision_timeout: float = 120.0) -> LLMProvider:
    if cfg.provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        key, _ = credentials.resolve("anthropic", world_id)
        return AnthropicProvider(
            model=cfg.model, timeout_seconds=cfg.request_timeout_seconds, max_retries=cfg.max_retries,
            effort=cfg.effort, server_side_fallback=cfg.server_side_fallback, prompt_caching=cfg.prompt_caching,
            api_key=key,
        )
    if cfg.provider == "openrouter":
        from .openrouter_provider import OpenRouterProvider

        key, _ = credentials.resolve("openrouter", world_id)
        model = cfg.model if "/" in cfg.model else OPENROUTER_DEFAULT_MODEL
        return OpenRouterProvider(model=model, api_key=key, timeout_seconds=cfg.request_timeout_seconds,
                                  max_retries=cfg.max_retries, effort=cfg.effort, prompt_caching=cfg.prompt_caching)
    if cfg.provider == "claude_code":
        from .claude_code_provider import ClaudeCodeProvider

        # The CLI accepts aliases ("sonnet", "haiku", "opus") or full model IDs.
        return ClaudeCodeProvider(model=cfg.model or CLAUDE_CODE_DEFAULT_MODEL, world_id=world_id, timeout_seconds=decision_timeout,
                                  effort=cfg.effort, session_mode=cfg.claude_code_session_mode)
    if cfg.provider == "mock":
        from .mock_provider import MockProvider

        return MockProvider(latency_seconds=cfg.mock_latency_seconds, failure_rate=cfg.mock_failure_rate,
                            invalid_output_rate=cfg.mock_invalid_output_rate, seed=cfg.mock_seed)
    raise ValueError(f"no LLM provider for '{cfg.provider}'")

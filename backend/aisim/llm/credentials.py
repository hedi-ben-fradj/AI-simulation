"""API keys for LLM providers.

A key typed on the setup page belongs to one world. It is held in this
process's memory only: it is never written to the database, logged, or
returned by the API. Without a world key, the server's environment variable
is used. After a backend restart, worlds fall back to the environment (or the
user enters the key again on the world's LLM tab).
"""

from __future__ import annotations

import os

# Environment variables checked per provider, in order.
ENV_VARS: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_API_TOKEN"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_API_TOKEN"),
}

_world_keys: dict[str, str] = {}


def set_world_key(world_id: str, key: str | None) -> None:
    key = (key or "").strip()
    if key:
        _world_keys[world_id] = key
    else:
        _world_keys.pop(world_id, None)


def forget_world(world_id: str) -> None:
    _world_keys.pop(world_id, None)


def env_key(provider: str) -> str | None:
    for name in ENV_VARS.get(provider, ()):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def resolve(provider: str, world_id: str | None) -> tuple[str | None, str]:
    """Return ``(key, source)``; source is ``world``, ``server`` or ``missing``."""
    if provider not in ENV_VARS:
        return None, "not_needed"
    if world_id and world_id in _world_keys:
        return _world_keys[world_id], "world"
    key = env_key(provider)
    return (key, "server") if key else (None, "missing")


def server_keys() -> dict[str, bool]:
    """Which providers have a key in the server environment (never the key itself)."""
    return {provider: env_key(provider) is not None for provider in ENV_VARS}

"""Configuration loading: YAML presets plus deep-merged overrides."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from .schema import SimulationConfig

PRESET_DIR = Path(__file__).parent / "presets"

__all__ = ["SimulationConfig", "load_config", "list_presets", "deep_merge", "PRESET_DIR"]


def deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``base`` with ``overrides`` merged in recursively."""
    result = copy.deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def list_presets() -> list[dict[str, str]]:
    presets = []
    for path in sorted(PRESET_DIR.glob("*.yaml")):
        data = _read_yaml(path)
        presets.append(
            {"id": path.stem, "name": data.get("name", path.stem), "description": data.get("description", "")}
        )
    return presets


def load_config(
    preset: str | Path | None = "default", overrides: dict[str, Any] | None = None
) -> SimulationConfig:
    """Load a preset (by name or path), apply overrides and validate.

    Non-default presets inherit from ``default.yaml`` and only list what they
    change.
    """
    data = _read_yaml(PRESET_DIR / "default.yaml")
    if preset is not None:
        path = Path(preset)
        if not path.suffix:
            path = PRESET_DIR / f"{preset}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Unknown preset: {preset}")
        if path.resolve() != (PRESET_DIR / "default.yaml").resolve():
            data = deep_merge(data, _read_yaml(path))
    data = deep_merge(data, overrides or {})
    level = data.get("resource_level")
    if level:
        # A resource level derives economy values from the population; values
        # set explicitly in ``overrides`` still win.
        from .levels import resource_overrides

        explicit = {k: v for k, v in (overrides or {}).items() if k != "resource_level"}
        data = deep_merge(deep_merge(data, resource_overrides(level, data)), explicit)
    return SimulationConfig.model_validate(data)

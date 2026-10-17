"""Experiment specification."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class Condition(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    preset: str | None = None  # defaults to the experiment's base preset
    overrides: dict[str, Any] = Field(default_factory=dict)


class ExperimentSpec(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    base_preset: str = "default"
    base_overrides: dict[str, Any] = Field(default_factory=dict)
    conditions: list[Condition] = Field(..., min_length=1, max_length=12)
    seeds: list[int] = Field(default_factory=lambda: [1, 2, 3], min_length=1, max_length=50)
    ticks: int = Field(24 * 7, ge=1, le=24 * 365)
    # Condition used as the reference in comparisons (default: the first).
    baseline: str | None = None
    parallel_runs: int = Field(2, ge=1, le=8)
    # Stop launching LLM runs once total experiment spend reaches this (USD).
    maximum_total_spend: float | None = 20.0

    @model_validator(mode="after")
    def _check(self) -> "ExperimentSpec":
        names = [c.name for c in self.conditions]
        if len(set(names)) != len(names):
            raise ValueError("condition names must be unique")
        if self.baseline is not None and self.baseline not in names:
            raise ValueError("baseline must name a condition")
        return self

    @property
    def baseline_name(self) -> str:
        return self.baseline or self.conditions[0].name

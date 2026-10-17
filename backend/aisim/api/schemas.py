"""Typed request bodies for the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, SecretStr


class CreateWorldRequest(BaseModel):
    preset: str = "default"
    name: str | None = Field(None, max_length=200)
    overrides: dict[str, Any] = Field(default_factory=dict)
    start: bool = False
    # Provider key for this world only (kept in server memory, never stored).
    api_key: SecretStr | None = Field(None, max_length=400)


class CredentialsRequest(BaseModel):
    api_key: SecretStr = Field(..., min_length=1, max_length=400)


class StepRequest(BaseModel):
    count: int = Field(1, ge=1, le=500)


class SpeedRequest(BaseModel):
    speed: float = Field(..., ge=0, le=100)

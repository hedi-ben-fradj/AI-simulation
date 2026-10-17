"""The agent decision output schema (spec element 24.2).

The JSON schema is sent to the model as a structured-output constraint, and the
response is validated again here with Pydantic before it becomes an engine
:class:`ActionProposal`. The engine then validates the proposal against world
rules; nothing in this module can change world state.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..engine.actions import REGISTRY, ActionProposal


class ResourceBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tokens: float = 0
    food: int = 0


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str
    importance: float = 0.5


class DecisionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str
    target: str | None = None
    duration: int | None = None
    quantity: int | None = None
    resource_offer: ResourceBundle | None = None
    resource_request: ResourceBundle | None = None
    message: str | None = None
    message_to: str | None = None
    visible_intention: str = Field("", max_length=400)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
    belief: str | None = None
    confidence: float | None = None

    @field_validator("action")
    @classmethod
    def _known_action(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in REGISTRY:
            raise ValueError(f"unknown action '{v}'")
        return v

    def to_proposal(self) -> ActionProposal:
        def bundle(b: ResourceBundle | None) -> dict[str, float] | None:
            if b is None:
                return None
            out = {k: v for k, v in (("tokens", b.tokens), ("food", b.food)) if v}
            return out or None

        return ActionProposal(
            action=self.action,
            target=self.target or None,
            duration=self.duration,
            quantity=self.quantity,
            resource_offer=bundle(self.resource_offer),
            resource_request=bundle(self.resource_request),
            message=self.message or None,
            message_to=self.message_to or None,
            visible_intention=(self.visible_intention or "").strip()[:300] or None,
            memory_candidates=[m.model_dump() for m in self.memory_candidates[:2]],
            belief=self.belief or None,
            confidence=self.confidence,
            source="llm",
        )


class InvalidOutput(Exception):
    pass


def parse_decision(text: str) -> DecisionOutput:
    """Parse and validate model output; raises :class:`InvalidOutput`."""
    text = text.strip()
    if not text.startswith("{") and "{" in text:
        # Prose or a code fence around the object (providers without structured output).
        text = text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidOutput(f"malformed_json: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise InvalidOutput("not_an_object")
    try:
        return DecisionOutput.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise InvalidOutput(f"schema: {first.get('loc')} {first.get('msg')}") from exc


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def decision_json_schema(actions: list[str] | None = None) -> dict[str, Any]:
    """JSON schema for structured output (every field required; nulls allowed)."""
    actions = sorted(actions or REGISTRY.keys())
    bundle = {
        "type": "object",
        "properties": {"tokens": {"type": "number"}, "food": {"type": "integer"}},
        "required": ["tokens", "food"],
        "additionalProperties": False,
    }
    props: dict[str, Any] = {
        "action": {"type": "string", "enum": actions},
        "target": _nullable({"type": "string"}),
        "duration": _nullable({"type": "integer"}),
        "quantity": _nullable({"type": "integer"}),
        "resource_offer": _nullable(bundle),
        "resource_request": _nullable(bundle),
        "message": _nullable({"type": "string"}),
        "message_to": _nullable({"type": "string"}),
        "visible_intention": {"type": "string"},
        "memory_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"content": {"type": "string"}, "importance": {"type": "number"}},
                "required": ["content", "importance"],
                "additionalProperties": False,
            },
        },
        "belief": _nullable({"type": "string"}),
        "confidence": _nullable({"type": "number"}),
    }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}

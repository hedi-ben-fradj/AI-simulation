"""World events.

Every consequential change is recorded as an event. Events carry a visibility
so that agents only learn about what they could plausibly observe:

* ``public``   - observable by agents within perception radius of ``location``.
* ``private``  - known only to the listed ``participants``.
* ``system``   - bookkeeping visible to the researcher UI only.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel):
    tick: int
    type: str
    summary: str
    agent_id: str | None = None
    target_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    visibility: str = "public"
    participants: list[str] = Field(default_factory=list)
    x: float | None = None
    y: float | None = None
    importance: float = 0.3

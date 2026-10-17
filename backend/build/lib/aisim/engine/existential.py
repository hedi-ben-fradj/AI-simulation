"""The universal existential goal: understanding why one exists.

Contemplation is not forced. At each decision opportunity the engine computes

    p = clamp(p_base + kS*S + kN*N + kX*X + kD*D + kF*F - kO*O, p_min, p_max)

and samples activation from the dedicated ``existential`` random stream.
Spirituality changes how *often* the question becomes salient, never what
conclusion the agent reaches.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .state import Agent

if TYPE_CHECKING:  # pragma: no cover
    from ..config.schema import ExistentialSection

EXISTENTIAL_PATTERN = re.compile(
    r"\b(exist\w*|purpose|meaning of|meaningful|why (am i|are we|do we)|soul|conscious\w*|"
    r"god|gods|divine|afterlife|spirit\w*|universe|transcend\w*|creator|mortality|"
    r"what are we)\b",
    re.IGNORECASE,
)


def is_existential_text(text: str | None) -> bool:
    return bool(text) and bool(EXISTENTIAL_PATTERN.search(text))


def _c(v: float) -> float:
    return max(0.0, min(1.0, v))


def activation_probability(cfg: "ExistentialSection", S: float, N: float, X: float, D: float,
                           F: float, O: float) -> float:
    p = (
        cfg.base_probability
        + cfg.spirituality_coefficient * _c(S)
        + cfg.novelty_coefficient * _c(N)
        + cfg.stress_coefficient * _c(X)
        + cfg.social_discussion_coefficient * _c(D)
        + cfg.free_time_coefficient * _c(F)
        - cfg.overload_coefficient * _c(O)
    )
    return max(cfg.minimum_probability, min(cfg.maximum_probability, p))


def activation_inputs(agent: Agent, free_attention: float, needs_ok: bool) -> dict[str, float]:
    ex = agent.existential
    stress = agent.emotion("stress")
    return {
        "S": agent.personality.get("spirituality", 0.5),
        "N": _c(ex.novelty),
        "X": _c(0.6 * stress + 0.4 * ex.uncertainty),
        "D": _c(ex.discussion_exposure),
        "F": _c(free_attention * (1.0 if needs_ok else 0.3)),
        "O": _c(agent.emotion("overload")),
    }


def decay_signals(cfg: "ExistentialSection", agent: Agent) -> None:
    ex = agent.existential
    k = 1 - cfg.signal_decay_per_tick
    ex.novelty = round(ex.novelty * k, 5)
    ex.discussion_exposure = round(ex.discussion_exposure * k, 5)
    ex.uncertainty = round(ex.uncertainty * k, 5)

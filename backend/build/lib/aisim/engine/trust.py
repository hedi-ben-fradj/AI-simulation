"""Directed trust using a Beta-distribution model.

Each agent holds ``Beta(alpha, beta)`` about every agent it knows. Trust is the
posterior mean ``alpha / (alpha + beta)``. Positive evidence adds to alpha,
negative evidence to beta, each bounded by ``maximum_evidence_weight``. Trust
only changes when the truster itself receives relevant evidence (it took part
in, or observed, the interaction).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .state import Agent, Relationship

if TYPE_CHECKING:  # pragma: no cover
    from ..config.schema import TrustSection


def new_relationship(cfg: "TrustSection", other: Agent, tick: int) -> Relationship:
    return Relationship(
        other_id=other.id,
        other_name=other.name,
        trust_alpha=cfg.prior_alpha,
        trust_beta=cfg.prior_beta,
        first_met_tick=tick,
        last_interaction_tick=tick,
    )


def trust_value(alpha: float, beta: float) -> float:
    return alpha / (alpha + beta)


def apply_evidence(cfg: "TrustSection", rel: Relationship, positive: bool, weight: float) -> tuple[float, float]:
    """Update ``rel`` in place. Returns (trust_before, trust_after)."""
    before = rel.trust
    w = max(0.0, min(weight, cfg.maximum_evidence_weight))
    if positive:
        rel.trust_alpha += w
    else:
        rel.trust_beta += w
    return before, rel.trust


def decay_towards_prior(cfg: "TrustSection", rel: Relationship, days: float = 1.0) -> None:
    """Optional forgetting: move alpha/beta part of the way back to the prior."""
    if not cfg.enable_time_decay:
        return
    f = min(1.0, cfg.decay_rate_per_day * days)
    rel.trust_alpha += (cfg.prior_alpha - rel.trust_alpha) * f
    rel.trust_beta += (cfg.prior_beta - rel.trust_beta) * f

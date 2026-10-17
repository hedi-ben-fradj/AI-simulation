"""Gradual, bounded personality change from accumulated evidence.

Behaviour produces *evidence* (a target value and a weight) rather than direct
trait changes. Evidence accumulates and is applied once per update interval:

    target         = weighted mean of evidence targets
    evidence_weight = min(1, total_weight / evidence_saturation)
    x_new = clamp(x_old + learning_rate * evidence_weight * (target - x_old), 0, 1)

with the change additionally capped at ``maximum_change_per_event``. Callers
lower the evidence weight when behaviour is need-driven (e.g. a starving agent
stealing food says less about its character than a well-fed one).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .state import Agent

if TYPE_CHECKING:  # pragma: no cover
    from ..config.schema import PersonalitySection


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def trait_update(cfg: "PersonalitySection", x_old: float, target: float, evidence_weight: float) -> float:
    delta = cfg.learning_rate * clamp(evidence_weight) * (target - x_old)
    cap = cfg.maximum_change_per_event
    delta = max(-cap, min(cap, delta))
    return clamp(x_old + delta)


def add_evidence(agent: Agent, trait: str, target: float, weight: float) -> None:
    if weight <= 0 or trait not in agent.personality:
        return
    acc = agent.trait_evidence.setdefault(trait, [0.0, 0.0])
    acc[0] += clamp(target) * weight
    acc[1] += weight


def apply_accumulated(cfg: "PersonalitySection", agent: Agent, tick: int) -> list[dict[str, Any]]:
    changes = []
    for trait, (weighted_sum, total_weight) in sorted(agent.trait_evidence.items()):
        if total_weight <= 0:
            continue
        target = weighted_sum / total_weight
        ew = min(1.0, total_weight / cfg.evidence_saturation)
        old = agent.personality[trait]
        new = round(trait_update(cfg, old, target, ew), 5)
        if abs(new - old) > 1e-9:
            agent.personality[trait] = new
            changes.append({
                "agent_id": agent.id, "tick": tick, "trait": trait, "old": old, "new": new,
                "target": round(target, 4), "evidence_weight": round(ew, 4),
            })
    agent.trait_evidence = {}
    return changes

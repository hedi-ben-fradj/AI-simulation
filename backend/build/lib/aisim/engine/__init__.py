"""Deterministic simulation engine (authoritative world state and rules)."""

from . import social as _social  # noqa: F401  (registers social actions)
from .actions import REGISTRY, ActionProposal
from .simulation import DecisionRecord, DecisionRequest, Simulation, TickResult
from .state import TRAITS, Agent, WorldState

__all__ = [
    "REGISTRY", "ActionProposal", "DecisionRecord", "DecisionRequest", "Simulation", "TickResult",
    "TRAITS", "Agent", "WorldState",
]

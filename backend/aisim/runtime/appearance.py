"""How an agent looks in the UI (purely presentational; never used by the engine).

The character sprite reflects the agent's strongest *starting* trait, so it is
stable for the agent's whole life even as personality drifts. The colour
variant is picked from the agent id so similar agents remain distinguishable.
When no trait stands out (e.g. identical personalities) appearance is varied by id.
"""

from __future__ import annotations

import hashlib

# Archetype -> sprite sheets (files in frontend/public/sprites/characters/).
ARCHETYPES: dict[str, list[str]] = {
    "mage": ["mage-red", "mage-cyan"],
    "archer": ["archer-green", "archer-purple"],
    "warrior": ["warrior-red", "warrior-blue"],
    "soldier": ["soldier-blue", "soldier-yellow", "soldier-red"],
    "villager": ["human-worker-red", "human-worker-cyan"],
    "guard": ["human-soldier-cyan", "human-soldier-red"],
    "orc": ["orc-peon-red", "orc-peon-cyan", "orc-grunt", "orc-soldier-red", "orc-soldier-cyan"],
}

TRAIT_ARCHETYPE: dict[str, str] = {
    "spirituality": "mage", "scientific_curiosity": "mage", "artistic": "mage",
    "curiosity": "archer", "risk_tolerance": "archer",
    "ambition": "warrior", "competitiveness": "warrior",
    "persistence": "soldier",
    "agreeableness": "villager", "sociability": "villager", "generosity": "villager", "empathy": "villager",
    "humor": "villager", "honesty": "guard", "impulsivity": "guard",
    "criminal_tendency": "orc",
}
# Without a standout trait, never use orcs (they signal a criminal tendency).
NEUTRAL_POOL = [s for a in ("villager", "guard", "archer", "mage", "soldier", "warrior") for s in ARCHETYPES[a]]
STANDOUT = 0.08


def _pick(options: list[str], key: str) -> str:
    h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    return options[h % len(options)]


def archetype(traits: dict[str, float]) -> str | None:
    if not traits:
        return None
    trait, value = max(((t, v) for t, v in traits.items() if t in TRAIT_ARCHETYPE), key=lambda kv: (kv[1], kv[0]),
                       default=(None, 0.0))
    if trait is None or value - 0.5 < STANDOUT:
        return None
    return TRAIT_ARCHETYPE[trait]


def agent_sprite(agent_id: str, initial_traits: dict[str, float]) -> str:
    kind = archetype(initial_traits)
    if kind is None:
        return _pick(NEUTRAL_POOL, agent_id)
    return _pick(ARCHETYPES[kind], agent_id)

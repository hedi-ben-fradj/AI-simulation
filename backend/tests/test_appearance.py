from pathlib import Path

from aisim.runtime.appearance import ARCHETYPES, NEUTRAL_POOL, agent_sprite

SPRITES = Path(__file__).resolve().parents[2] / "frontend" / "public" / "sprites" / "characters"


def test_every_sprite_exists():
    for sheets in ARCHETYPES.values():
        for s in sheets:
            assert (SPRITES / f"{s}.png").exists(), s


def test_dominant_trait_picks_archetype():
    base = {t: 0.5 for t in ("spirituality", "criminal_tendency", "sociability", "curiosity")}
    assert agent_sprite("a1", {**base, "spirituality": 0.9}).startswith("mage")
    assert agent_sprite("a1", {**base, "criminal_tendency": 0.9}).startswith("orc")
    assert agent_sprite("a1", {**base, "curiosity": 0.8}).startswith("archer")


def test_identical_personalities_are_varied_and_never_orcs():
    flat = {"criminal_tendency": 0.5, "spirituality": 0.5}
    sprites = {agent_sprite(f"a{i}", flat) for i in range(1, 20)}
    assert len(sprites) > 3 and all(s in NEUTRAL_POOL for s in sprites)


def test_sprite_is_stable():
    t = {"ambition": 0.8}
    assert agent_sprite("a3", t) == agent_sprite("a3", t)

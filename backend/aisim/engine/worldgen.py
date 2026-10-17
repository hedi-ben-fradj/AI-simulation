"""Initial world and agent generation from configuration."""

from __future__ import annotations

import math
import uuid

from ..config import SimulationConfig
from .rng import RandomStreams
from .state import EMOTIONS, TRAITS, Agent, Location, WorldState

NAMES = [
    "Ada", "Bo", "Cyra", "Dax", "Eli", "Fen", "Gia", "Hal", "Ivo", "Juno",
    "Kai", "Lior", "Mara", "Nico", "Oren", "Pia", "Quin", "Rhea", "Sol", "Tova",
    "Uma", "Vey", "Wren", "Xan", "Yara", "Zed", "Arlo", "Bria", "Cato", "Dena",
    "Ezra", "Faye", "Gus", "Hana", "Isak", "Jade", "Kian", "Lena", "Milo", "Nell",
]

BACKGROUNDS = [
    "grew up near the fields and values steady work",
    "is a newcomer who arrived with a few belongings",
    "used to keep records for the settlement",
    "was raised by a large family and enjoys company",
    "spent years wandering before settling here",
    "is known for fixing things and asking questions",
    "has always been drawn to stories and songs",
    "prefers quiet mornings and long walks",
    "once ran a small market stall",
    "is fascinated by how the world works",
]

_LOCATION_NAMES = {
    "workplace": ["Workshop", "Quarry", "Mill", "Forge"],
    "food": ["Market", "Orchard", "Granary", "Fishery"],
    "rest": ["Lodge", "Shelter", "Haven", "Cabins"],
    "gathering": ["Plaza", "Commons", "Fireside"],
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def generate_locations(config: SimulationConfig, rng) -> dict[str, Location]:
    wc = config.world
    rc = config.resources
    locations: dict[str, Location] = {}
    if wc.locations:
        for i, spec in enumerate(wc.locations):
            lid = f"loc{i + 1}"
            locations[lid] = Location(id=lid, **spec.model_dump())
        return _fill_location_defaults(locations, config)

    counts = [
        ("workplace", wc.workplaces),
        ("food", wc.food_sources),
        ("rest", wc.rest_areas),
        ("gathering", wc.gathering_areas),
    ]
    total = sum(c for _, c in counts)
    # Place locations on a jittered ring so travel distances are comparable.
    cx, cy = wc.width / 2, wc.height / 2
    radius = min(wc.width, wc.height) * 0.32
    slots = list(range(total))
    rng.shuffle(slots)
    idx = 0
    for ltype, count in counts:
        for k in range(count):
            slot = slots[idx]
            idx += 1
            angle = 2 * math.pi * slot / max(1, total) + rng.uniform(-0.15, 0.15)
            r = radius * rng.uniform(0.75, 1.1)
            if ltype == "gathering" and k == 0:
                x, y = cx, cy
            else:
                x, y = cx + r * math.cos(angle), cy + r * math.sin(angle)
            names = _LOCATION_NAMES[ltype]
            name = names[k % len(names)] + ("" if k < len(names) else f" {k // len(names) + 1}")
            lid = f"loc{len(locations) + 1}"
            locations[lid] = Location(id=lid, name=name, type=ltype, x=round(x, 2), y=round(y, 2))
    return _fill_location_defaults(locations, config)


def _fill_location_defaults(locations: dict[str, Location], config: SimulationConfig) -> dict[str, Location]:
    wc, rc = config.world, config.resources
    for loc in locations.values():
        if loc.type == "workplace" and loc.capacity is None:
            loc.capacity = wc.workplace_capacity
        if loc.type == "food":
            if loc.max_stock is None:
                loc.max_stock = wc.food_stock_per_source
            if loc.stock is None:
                loc.stock = loc.max_stock
            if loc.restock_per_day is None:
                loc.restock_per_day = wc.food_restock_per_day
            if loc.price is None:
                loc.price = rc.food_price
    return locations


def generate_personality(config: SimulationConfig, rng) -> dict[str, float]:
    pc = config.personality
    traits: dict[str, float] = {}
    for trait in TRAITS:
        mean = pc.trait_means.get(trait, pc.initial_default)
        if pc.initial_distribution == "default":
            value = mean
        elif pc.initial_distribution == "uniform":
            value = rng.uniform(mean - pc.initial_spread, mean + pc.initial_spread)
        else:
            value = rng.gauss(mean, pc.initial_spread)
        traits[trait] = round(_clamp(value), 3)
    return traits


def create_agent(config: SimulationConfig, streams: RandomStreams, index: int, tick: int = 0,
                 controller: str = "rule", name: str | None = None) -> Agent:
    rng = streams["init"]
    rc, cc = config.resources, config.capacity
    var = cc.capacity_variation

    def vary(v: float) -> float:
        return v * (1 + rng.uniform(-var, var)) if var > 0 else v

    personality = generate_personality(config, rng)
    emotions = {e: 0.0 for e in EMOTIONS}
    emotions["happiness"] = 0.5
    emotions["safety"] = 0.7
    if name is None:
        name = NAMES[index % len(NAMES)] + ("" if index < len(NAMES) else f" {index // len(NAMES) + 1}")
    return Agent(
        id=f"a{index + 1}",
        name=name,
        background=BACKGROUNDS[rng.randrange(len(BACKGROUNDS))],
        controller=controller,
        x=round(rng.uniform(0.2, 0.8) * config.world.width, 2),
        y=round(rng.uniform(0.2, 0.8) * config.world.height, 2),
        born_tick=tick,
        personality=personality,
        initial_personality=dict(personality),
        tokens=rc.starting_tokens,
        food=rc.starting_food,
        energy=rc.starting_energy,
        health=rc.starting_health,
        hunger=rc.starting_hunger,
        emotions=emotions,
        attention_capacity=round(vary(cc.attention_budget_per_tick), 2),
        communication_capacity=max(1, round(vary(cc.max_outgoing_messages_per_tick))),
        work_capacity=max(1, round(vary(config.work.max_work_ticks_per_day))),
    )


def assign_controllers(config: SimulationConfig, count: int) -> list[str]:
    if config.llm.provider == "none":
        return ["rule"] * count
    n_llm = count if config.llm.llm_agents is None else min(count, config.llm.llm_agents)
    return ["llm"] * n_llm + ["rule"] * (count - n_llm)


def generate_world(config: SimulationConfig, world_id: str | None = None,
                   streams: RandomStreams | None = None) -> tuple[WorldState, RandomStreams]:
    streams = streams or RandomStreams(config.simulation.random_seed)
    population = min(config.simulation.population, config.simulation.max_agents)
    locations = generate_locations(config, streams["init"])
    controllers = assign_controllers(config, population)
    agents = {}
    for i in range(population):
        agent = create_agent(config, streams, i, controller=controllers[i])
        agents[agent.id] = agent
    world = WorldState(
        id=world_id or uuid.uuid4().hex[:12],
        name=config.name,
        width=config.world.width,
        height=config.world.height,
        locations=locations,
        agents=agents,
        counters={"a": population},
    )
    return world, streams

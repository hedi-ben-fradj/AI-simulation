import pytest

from aisim.config import load_config
from aisim.engine import Simulation
from aisim.engine.actions import ActionProposal


def make_sim(overrides=None, preset="default"):
    base = {"simulation": {"population": 3}, "personality": {"initial_distribution": "default"}}
    from aisim.config import deep_merge

    cfg = load_config(preset, deep_merge(base, overrides or {}))
    return Simulation.create(cfg, "test")


def place(sim, agent, loc_type):
    loc = next(l for l in sim.world.locations.values() if l.type == loc_type)
    agent.x, agent.y = loc.x, loc.y
    return loc


def run_action(sim, agent_id, proposal: ActionProposal, others=None):
    """Run one tick where ``agent_id`` proposes ``proposal`` and others idle."""
    requests = sim.begin_tick()
    proposals = {r.agent_id: ActionProposal(action="idle") for r in requests}
    proposals.update(others or {})
    if any(r.agent_id == agent_id for r in requests):
        proposals[agent_id] = proposal
    records = sim.apply_decisions(proposals)
    result = sim.advance()
    return result, {r.agent_id: r for r in records}


@pytest.fixture
def sim():
    return make_sim()

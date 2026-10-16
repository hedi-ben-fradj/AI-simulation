# AI Agent Civilization Simulation

A web-based, multi-agent civilization simulation in which a population of
agents lives in a small 2D world. Agents can be driven by a rule-based policy or
by real LLM calls (Anthropic Claude). The **simulation engine is authoritative**:
the LLM only *proposes* actions; deterministic world rules decide what actually
happens.

> This is an experimental simulation. It makes no claim that agents are
> conscious or sentient. Its purpose is to observe behaviour that emerges from
> defined rules, agent architectures, environmental conditions and LLM decisions.

## Repository layout

```
backend/            Python package `aisim`
  aisim/config/     Typed configuration + YAML presets (default, scarcity, abundance, ...)
  aisim/engine/     Deterministic simulation engine (world state, actions, validation,
                    needs, death, communication, trust, personality, existential goal,
                    rule-based policy, metrics)
  tests/            pytest suite
frontend/           React + TypeScript + Vite + PixiJS client
docs/               Architecture and experiment documentation
```

## Quick start (engine only)

```bash
cd backend
pip install -e ".[dev]"
python -m pytest -q
```

```python
from aisim.config import load_config
from aisim.engine import Simulation

sim = Simulation.create(load_config("scarcity"))
for _ in range(24 * 7):          # one simulated week (24 ticks/day)
    result = sim.step()           # rule-based agents
print(result.metrics)
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design and
[`docs/RULES.md`](docs/RULES.md) for every world rule and formula.

## Running the full application

Prerequisites: Python 3.11+, Node 20+, PostgreSQL 14+ (or use SQLite for a quick try).

```bash
# 1. Backend
cd backend
pip install -e ".[dev]"
cp .env.example .env            # edit DATABASE_URL; optionally ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)
python -m aisim                 # http://127.0.0.1:8000 (runs migrations on startup)

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api and /ws to the backend)
```

Open http://localhost:5173, click **New world**, choose a preset and run it.
Without `DATABASE_URL`, the backend uses a local SQLite file (`backend/aisim.db`).

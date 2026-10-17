# AI Agent Civilization Simulation

A web application in which a population of agents lives in a small 2D world.
Agents have personalities, needs, finite time, energy and attention, memories and
directed trust in each other. Their decisions come from a rule-based policy or from
**Claude** via the Anthropic API. A deterministic simulation engine decides what
actually happens.

> **The LLM proposes; the engine decides.** That separation makes the world
> controllable, measurable, testable and suitable for experiments.
>
> This is an experimental simulation. It makes no claim that agents are conscious
> or sentient; it observes behaviour that emerges from defined rules, agent
> architectures, environments and model decisions.

## Quick start

```bash
ANTHROPIC_API_KEY=sk-ant-...  docker compose up --build    # the key is optional
# open http://localhost:8080 → New world → pick a preset → Run
```

Without Docker see [`docs/OPERATIONS.md`](docs/OPERATIONS.md). Engine only:

```python
from aisim.config import load_config
from aisim.engine import Simulation

sim = Simulation.create(load_config("scarcity"))
for _ in range(24 * 7):          # one simulated week (24 ticks/day)
    result = sim.step()           # rule-based agents
print(result.metrics)
```

## What you can do

* **Watch a world** — live PixiJS map with movement, mood colours, speech and
  intention bubbles; run, pause, step, change speed.
* **Inspect agents** — state, needs, temporary emotions, goals, time allocation,
  personality (and its drift), relationships and the trust evidence behind them,
  memories, every decision (LLM, rule or fallback, with rejection reasons), and
  stated beliefs about purpose.
* **Study society** — trust network, trust matrix, conversations, friendships,
  hostility, network density.
* **Measure minds** — do traits change behaviour? Pre-registered trait ↔ behaviour
  hypotheses, spirituality vs existential activation, population trait drift.
* **Run experiments** — conditions × seeds (e.g. scarcity vs abundance), mean ±
  95% CI, Welch t-tests, overlays, CSV/JSON export; in the UI or headless.
* **Use Claude** — per-agent LLM control with structured output, cached prompts,
  context budgets, information boundaries, concurrency/rate limits, timeouts with
  fallback, and spend caps. Real API cost is tracked separately from in-world cost.

## Documentation

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | components, tick lifecycle, persistence, information boundaries, extension points |
| [`docs/RULES.md`](docs/RULES.md) | every world rule and formula (needs, actions, validation, communication, trust, personality, existential goal, death) |
| [`docs/LLM.md`](docs/LLM.md) | Claude-driven agents: prompt, context, failure handling, cost |
| [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) | experiment specs, measures, statistics, templates |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | deployment, configuration, recovery, performance |
| [`docs/SECURITY.md`](docs/SECURITY.md) | secrets, API protection, prompt-injection defences |

## Repository layout

```
backend/                 Python 3.11+, FastAPI, SQLAlchemy, Alembic
  aisim/engine/          authoritative deterministic simulation
  aisim/agents/          LLM decision service (context, prompt, memory, schema)
  aisim/llm/             provider abstraction (Anthropic, mock)
  aisim/runtime/         world runners, WebSocket hub
  aisim/api/             REST + WebSocket API
  aisim/persistence/     models, migrations, repository
  aisim/analysis/        behaviour measurement
  aisim/experiments/     experiment runner, statistics, CLI
  aisim/config/          typed config + presets (default, scarcity, abundance, mock_llm, first_milestone_llm)
  scripts/stress_test.py performance measurement
  tests/                 unit, integration and live-LLM tests
frontend/                React + TypeScript + Vite + Mantine + PixiJS + Recharts
docker-compose.yml       PostgreSQL + backend + frontend
```

## First-version checklist (spec element 26)

| Area | Status |
|---|---|
| World simulation: configurable world, distinct agents, ticks, limited actions, hunger/health/energy/money/inventory/time, work/eat/rest/socialise/explore/reflect, death, enforced costs | ✅ |
| AI agents: provider-backed proposals, validation, short-term context + persistent memories, private/public boundaries, personalities, existential goal without dominance, timeouts/rate limits/invalid output handled | ✅ (live runs need `ANTHROPIC_API_KEY`) |
| Social: communication with send/process costs, directed trust updated by observed evidence, cooperation/trade/help/refusal/conflict, events | ✅ |
| Persistence: PostgreSQL, events, messages, memories, relationships, trait history, LLM usage, resume after restart, event inspection | ✅ |
| Visualisation: 2D world, movement, intention bubbles, agent inspector, events/messages, population/economy/health statistics | ✅ |
| Experiments: ≥2 resource environments, repeated seeds, comparisons, recorded config/model settings, metric export | ✅ |

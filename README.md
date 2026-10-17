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

## Run it on your computer

The app runs entirely on your machine: a Python server (simulation + API) and a
web page you open in your browser. No account, database server or API key is
needed for the default rule-based agents.

### 1. Install the prerequisites (once)

| Tool | Version | Check with | Get it |
|---|---|---|---|
| Git | any | `git --version` | https://git-scm.com/downloads |
| Python | 3.11, 3.12 or 3.13 | `python3 --version` (Windows: `py --version`) | https://www.python.org/downloads/ — on Windows tick **"Add python.exe to PATH"** |
| Node.js | 20 or newer (LTS) | `node --version` | https://nodejs.org |

About 1 GB of free disk space is needed for dependencies.

### 2. Get the code

```bash
git clone https://github.com/hedi-ben-fradj/AI-simulation.git
cd AI-simulation
git checkout claude/dreamy-einstein-uwu2gt   # the branch with the app (skip once it is merged into main)
```

### 3a. Start it — one command (macOS and Linux)

```bash
./run.sh
```

The first run takes a few minutes: it creates a Python environment in
`backend/.venv`, installs the backend and frontend dependencies, builds the web
page, and starts the server. When you see

```
==> Starting on http://localhost:8000  (Ctrl+C to stop)
```

open **http://localhost:8000**. Later runs start in seconds. Stop with **Ctrl+C**;
your worlds are saved (in `backend/aisim.db`) and reappear the next time.

### 3b. Start it — step by step (Windows, or if you prefer doing it by hand)

Run these from the `AI-simulation` folder. No virtual-environment activation is
needed; the commands call the environment's Python directly.

**macOS / Linux**

```bash
# Backend: create an isolated Python environment and install the server
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -e "backend[dev]"

# Frontend: install and build the web page (once, and after updating the code)
cd frontend
npm ci
npm run build
cd ..

# Start (serves the API and the web page on one port)
cd backend
.venv/bin/python -m aisim
```

**Windows (PowerShell)**

```powershell
# Backend
py -3 -m venv backend\.venv
backend\.venv\Scripts\python -m pip install --upgrade pip
backend\.venv\Scripts\python -m pip install -e "backend[dev]"

# Frontend
cd frontend
npm ci
npm run build
cd ..

# Start
cd backend
.venv\Scripts\python -m aisim
```

Then open **http://localhost:8000**. To start again later, only the last two
lines are needed.

### 3c. Start it — with Docker (alternative)

If you have Docker Desktop, this runs the app with a PostgreSQL database and needs
no Python or Node.js:

```bash
docker compose up --build        # then open http://localhost:8080
```

### 4. Use it

1. The app opens on **Set up a simulation**. Choose the number of agents (2 or
   more), move the **Resources** slider between *Very scarce* and *Very abundant*,
   pick **Identical** personalities (everyone 50%) or **Randomised** with a
   deviation, and adjust the other settings. The right-hand panel previews the
   economy and every agent's starting traits.
2. Click **Start simulation**. Click an agent on the map (or in the list) to
   inspect it; use **Pause / Step / +1 day / speed** at the top.
3. The **Society**, **Mind** and **Analytics** tabs show relationships, whether
   traits drive behaviour, and population statistics. **Experiments** compares
   settings across several random seeds.

### Optional: let Claude decide for the agents

1. Get an API key at https://console.anthropic.com (API usage is billed by Anthropic).
2. Copy `backend/.env.example` to `backend/.env` and set
   `ANTHROPIC_API_KEY=sk-ant-...` (the server reads `.env` automatically; the key
   never reaches the browser).
3. Restart the server, and on the setup page choose **Agent minds → Claude**. Keep
   the **spend cap** set; the **LLM usage** tab shows requests and cost.

Tip: **Mock LLM (offline test)** exercises the same pipeline with no key and no cost.

### Optional: PostgreSQL instead of the built-in SQLite file

Create a database and put its address in `backend/.env`:

```
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/aisim
```

### For developers: hot reload and tests

```bash
./run.sh --dev                    # API on :8000 + auto-reloading UI on http://localhost:5173
# (manually: start the backend as above, then `cd frontend && npm run dev`)

cd backend && .venv/bin/python -m pytest -q          # backend tests
cd frontend && npm run typecheck && npm test         # frontend checks
```

### Troubleshooting

| Problem | Fix |
|---|---|
| `Python 3.11 or newer is required` / `python3: command not found` | Install Python from python.org. With several versions installed: `PYTHON=python3.12 ./run.sh`. |
| `Node.js … is too old` or `npm ci` fails | Install Node.js 20 LTS or newer, then delete `frontend/node_modules` and retry. |
| `address already in use` / port 8000 busy | Use another port: `PORT=8001 ./run.sh` (or `PORT=8001` in `backend/.env`) and open that port. |
| Page shows `{"detail":"Not Found"}` or the log says *frontend not built* | Run `npm run build` in `frontend/` (run.sh does this automatically). |
| Page does not update after pulling new code | Rebuild the UI (`./run.sh` does it when sources changed) and hard-refresh the browser. |
| Claude agents behave exactly like rule agents | The key is missing or invalid: check `backend/.env`, restart, and look at the **LLM usage** tab for errors. |
| `pip install` fails on Windows with a compiler error | Use Python 3.11–3.13 from python.org (not a pre-release). |
| Start from a clean slate | Stop the server and delete `backend/aisim.db`. |

### Engine only (no web page)

```python
from aisim.config import load_config
from aisim.engine import Simulation

sim = Simulation.create(load_config("default", {"resource_level": "scarce", "simulation": {"population": 3}}))
for _ in range(24 * 7):          # one simulated week (24 ticks/day)
    result = sim.step()           # rule-based agents
print(result.metrics)
```

## What you can do

* **Set up a world** — number of agents (from 2), a 7-step resource slider from
  very scarce to very abundant (scaled to the population), identical or randomised
  personalities with a chosen deviation from 50%, per-trait averages, message
  costs, trust towards strangers, theft, hazards, death/replacement, existential
  goal, and rule-based / mock / Claude minds, with a live preview of the economy
  and the agents' starting personalities.
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

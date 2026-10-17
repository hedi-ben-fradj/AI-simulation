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
2. Click **Start simulation**. The village appears as a pixel-art map: each agent
   is an animated character, places are buildings (workshop, market stall, tents,
   campfire) joined by dirt paths through the forest, and night falls every
   evening. **Drag** to pan, **scroll** (or **+ / −**) to zoom, **⤢** to see the
   whole map and **◎** to follow the selected agent. Click an agent on the map (or
   in the list) to inspect it; use **Pause / Step / +1 day / speed** at the top.
3. The **Society**, **Mind** and **Analytics** tabs show relationships, whether
   traits drive behaviour, and population statistics. **Experiments** compares
   settings across several random seeds.

### Optional: let an LLM decide for the agents

On the setup page, **Agent minds** offers four choices:

| Choice | What it uses | Cost |
|---|---|---|
| **Rule-based** | the built-in policy | free, reproducible |
| **Mock LLM (offline)** | the whole LLM pipeline with canned answers | free; for testing |
| **LLM provider API key** | **OpenRouter** (Claude, Gemini, GPT… with one key) or **Anthropic** | billed by the provider; capped per world |
| **Claude subscription** | the `claude` command (Claude Code) on the computer running the server, signed in with your Pro/Max plan | counts toward your plan's usage limits |

**With an API key.** Pick the provider, then paste the key into the
`OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` field. That key is used only for that
world and kept only in the server's memory: it is never saved to disk, logged or
sent back to the browser. After a server restart the world asks for it again on
its **LLM usage** tab. To avoid typing it, put it in `backend/.env` instead
(`OPENROUTER_API_KEY=sk-or-...` or `ANTHROPIC_API_KEY=sk-ant-...`) and leave the
field empty. Keys: https://openrouter.ai/keys or https://console.anthropic.com.
Good inexpensive models: `google/gemini-2.5-flash` (the OpenRouter default) or
`anthropic/claude-haiku-4.5`. Keep the **spend cap** set; the **LLM usage** tab
shows requests and the exact cost.

**With your Claude subscription.**
1. Install Claude Code (https://claude.com/claude-code) on the computer that runs
   the server, run `claude` once in a terminal and sign in with your Claude account.
2. If an `ANTHROPIC_API_KEY` is set in your shell, that's fine: the app removes it
   when it starts `claude`, so the subscription is used.
3. On the setup page choose **Claude subscription**, pick a model (`sonnet`,
   `haiku` or `opus`) and a conversation mode:
   * **One per agent (--resume)**: each agent has its own Claude Code conversation.
     The first decision starts it (`claude -p --session-id <id>`), later ones continue
     it (`claude -p --resume <id> …`), so the agent also remembers its earlier reasoning.
   * **Fresh each decision**: every decision is a new, unsaved conversation.
4. Each decision starts a `claude` process (a few seconds each), so keep the speed
   at 1× or lower. The **Wait per tick** setting (default 120 s) is how long a tick
   waits for answers before late agents use the rule-based policy for that tick.

The CLI runs with **all tools disabled**, no MCP servers, in an empty folder
(`~/.cache/aisim/claude-code/<world>`). Agents read each other's messages, so this
stops a message from making Claude run anything on your computer. To test the
setup without the UI: `cd backend && python scripts/llm_smoke_test.py --provider claude_code --model haiku --ticks 4`.

Tip: **Mock LLM (offline)** exercises the same pipeline with no key and no cost.

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
* **Watch a world** — live PixiJS pixel-art village: animated sprite characters
  (walking, working, resting, stealing, collapsing when they die) with names,
  mood dots, health bars, speech and intention bubbles; tile terrain with paths
  and forests, a day/night cycle with lit windows and a campfire; pan, zoom and
  follow; run, pause, step, change speed. Each agent's character class follows
  its strongest starting trait (mage = spiritual/scientific/artistic, archer =
  curious/risk-taking, warrior = ambitious/competitive, soldier = persistent,
  villager = social/kind, guard = honest/impulsive, orc = criminal tendency);
  agents with balanced personalities get a varied human look (never an orc).
* **Follow conversations** — the **💬 Conversations** panel (next to the villager
  list) lists who has been talking: pairs, and group conversations when several
  agents really talk among themselves. Open one, or pick any two or more agents,
  to read every message as a chat: who said what to whom and when, whether the
  recipient read it (or it expired unread), what the sender intended at the time,
  and their meetings, gifts, trades and thefts in between. The map focuses on
  them: they're highlighted and followed, everyone else is dimmed, and each new
  message flies as a letter from sender to recipient. A message line in the event
  feed, the **💬 Conversations** button in an agent's inspector and the Society
  tab all lead there.
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
  public/sprites/        character sheets and environment tiles (see Credits)
  src/sprites.ts         sheet layout, animations, texture loading
  src/terrain.ts         deterministic tile map (paths, clearings, forests)
  src/props.ts           pixel-art buildings and the campfire
docker-compose.yml       PostgreSQL + backend + frontend
```

## First-version checklist (spec element 26)

| Area | Status |
|---|---|
| World simulation: configurable world, distinct agents, ticks, limited actions, hunger/health/energy/money/inventory/time, work/eat/rest/socialise/explore/reflect, death, enforced costs | ✅ |
| AI agents: provider-backed proposals, validation, short-term context + persistent memories, private/public boundaries, personalities, existential goal without dominance, timeouts/rate limits/invalid output handled | ✅ (live runs need an Anthropic or OpenRouter key, or a Claude subscription) |
| Social: communication with send/process costs, directed trust updated by observed evidence, cooperation/trade/help/refusal/conflict, events | ✅ |
| Persistence: PostgreSQL, events, messages, memories, relationships, trait history, LLM usage, resume after restart, event inspection | ✅ |
| Visualisation: 2D world, movement, intention bubbles, agent inspector, events/messages, population/economy/health statistics | ✅ |
| Experiments: ≥2 resource environments, repeated seeds, comparisons, recorded config/model settings, metric export | ✅ |

## Credits

Character sprites and environment tiles come from the **Puny Characters** pixel-art
pack by Shade (32×32 characters, 16×16 tiles), stored under
`frontend/public/sprites/`. Check the pack's licence terms on its distribution
page before redistributing this project publicly. Buildings and the campfire are
drawn in code to match the pack's style.


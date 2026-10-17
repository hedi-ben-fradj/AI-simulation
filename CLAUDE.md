# CLAUDE.md — guide for the next agent

This file explains what this project is, the ideas it is built on, how the code is
organised, and the technical details and pitfalls you need before changing
anything. Read it fully before your first edit. The user-facing docs are
`README.md` (how to run it) and `docs/*.md` (rules, LLM, experiments, operations,
security, architecture). This file summarises them and adds what a developer
needs. If this file and the code disagree, the code wins; fix this file.

---

## 1. What the project is

**AI Agent Civilization Simulation**: a web app where a small community of agents
(2 or more; the setup page allows up to 50, configs up to 1000) lives in a 2D
world. Agents have personalities, needs (hunger, energy, health), money
("tokens"), limited time and attention, memories, directed trust in each other,
competing goals, and an optional existential goal ("why do I exist?"). The
researcher watches them live, inspects their minds, and runs controlled
experiments (e.g. scarcity vs abundance) across random seeds.

Agent decisions come from either a **deterministic rule policy** or **Claude**
(Anthropic API). Either way, the decision is only a *proposal*.

### The one rule: the LLM proposes; the engine decides

`backend/aisim/engine` is the only code that changes world state. It never
imports `aisim.llm` or `aisim.agents`. An agent returns an `ActionProposal`; the
engine validates it against the *current* state (`engine/validation.py`) and
applies deterministic consequences. Invalid proposals are rejected with a reason
(shown to the agent next time as `last_failure`) and replaced by a rule-based
fallback. No text an LLM writes can move resources by itself. Keep it this way.
It is what makes the simulation controllable, testable and reproducible, and it
is the main defence against prompt injection between agents.

It is a research and observation tool. It makes no claims about consciousness.
Only behaviour that comes out of explicit rules is observed.

### Origin and history

The user wrote the original spec ("Prompt_ai_simulation.md", ~46 KB, numbered
sections). **It is not in the repo.** Comments and docs that say "spec 22.3",
"spec 24.1/24.2" or "spec element 26" refer to its section numbers. The
README's "First-version checklist (spec element 26)" maps the spec's
requirements to the implementation.

Built in phases on branch `claude/dreamy-einstein-uwu2gt` (pushed after each
phase so no progress is lost):

1. Engine core (state, actions, needs, validation, rule policy, RNG streams)
2. Persistence (SQLAlchemy + Alembic), runtime (world runners), REST/WebSocket API
3. Frontend (React + PixiJS map, inspector, event feed, controls)
4. LLM agents (context builder, prompt, structured output, budgets, fallbacks)
5. Social layer (communication, trade, theft, Beta trust, relationships)
6. Mind (personality drift, goals, existential goal, behaviour analysis)
7. Experiments (conditions × seeds, statistics, exports, CLI, UI)
8. Robustness, performance, deployment, docs

Later user requests, all done:
- Small communities (2+ agents) and a **setup page** shown first: a 7-step
  resource slider, agent count, and personality modes. *Identical* means
  everyone at 50%. *Randomised* means a user-chosen deviation from 50%,
  normal or uniform.
- README with step-by-step local run instructions, `run.sh`, and the backend
  serving the built UI on one port.
- **Pixel-art UI overhaul** with the user-supplied "Puny Characters" sprite
  pack: animated character sprites for agents, a tile-based environment,
  pixel-art buildings, and day/night.

The user's style: short, informal requests ("overhaul the UI", "revise the
whole app"). Make reasonable decisions, verify end to end (screenshots for UI
work), and commit and push in meaningful steps. Don't open a PR unless asked.

---

## 2. Domain concepts (what the simulation models)

All numbers are configurable (`backend/aisim/config/schema.py` and YAML presets).
Every formula is in `docs/RULES.md`; this is the conceptual map.

### Time and ticks
- Discrete ticks; default `ticks_per_day = 24` (1 tick = 1 hour). Labels look
  like "Day 3, 14:00".
- Each tick has three phases (`engine/simulation.py`):
  1. `begin_tick()`: deliver messages, expire trade offers, allocate attention,
     sample existential activation, build a `DecisionRequest` for each agent
     that needs one (agents mid-task do not).
  2. `apply_decisions(proposals, meta)`: validate each proposal; commit it as a
     `Task` or reject it and use a fallback.
  3. `advance()`: run tasks (travel first), update needs and emotions, deaths,
     perception and observations, meetings, end-of-day rules (restock, upkeep,
     summaries), metrics. Returns a `TickResult` (events, messages, decisions,
     metrics).
- Agents act in a **seeded random order** each tick, so contested resources
  (food stock, job slots) are allocated fairly and reproducibly.
- One action starts per tick (1.0 unit of time). Actions can span several ticks
  as a committed **task**. Location- or target-bound actions travel first
  (`movement_speed_per_tick`). Travel over 8 ticks fails with
  `could_not_reach_target`. Arrival uses a small tolerance (0.05) so rounding
  can't strand agents.

### Agents (`engine/state.py: Agent`)
- **16 traits** in [0, 1] (`TRAITS`): artistic, scientific_curiosity, humor,
  agreeableness, sociability, spirituality, ambition, empathy, risk_tolerance,
  honesty, criminal_tendency, persistence, impulsivity, curiosity, generosity,
  competitiveness. `initial_personality` stores the birth traits, because
  traits drift.
- **Needs and resources**: hunger (rises each tick, starvation damages health),
  energy (drains, rest restores, exhaustion damages health), health (0 means
  death), tokens (money), food (inventory), knowledge (productivity bonus),
  artworks.
- **Emotions** (`EMOTIONS`): stress, happiness, frustration, loneliness,
  overload, curiosity_activation, safety. These give a `current_mood`:
  content, calm, curious, contemplative, lonely, stressed, frustrated,
  exhausted, starving, neutral.
- **Capacities**: attention budget per decision, messages per tick, work ticks
  per day.
- **Goals** (`engine/goals.py`): survival, economic, social, creative,
  scientific and existential. Salience comes from personality and state; only
  the top `max_active_goals` are active. Survival dominates when needs press.
- **Memory**: short-term observations, long-term `memories` (kind: event,
  reflection, belief, summary, observation, note; importance; tags; related
  agents), `life_summary` (daily summaries). The store is capped
  (`max_memories_per_agent`); old low-importance memories are consolidated.
  Retrieval (`agents/memory.py`) scores importance 0.5 + recency 0.3 +
  relevance 0.4.
- **Controller**: `rule` or `llm`. `llm.llm_agents` sets how many agents use
  the LLM (null means all).

### Actions (`engine/actions.py`, `REGISTRY` of `ActionSpec`)
`work, eat, buy_food, rest, explore, reflect, create, study, socialize, talk,
give, offer_trade, accept_trade, reject_trade, steal`, plus `idle`/`move`
internally. Each spec declares preconditions (`check`), duration limits,
per-tick effects (`tick` returns `"continue" | "done" | "failed:<reason>"`) and
costs. A new action registered there shows up automatically in prompts, the
output schema and the UI catalogue (`/api/catalog`).

Notable behaviours:
- `work`: wage × productivity. Fatigue and overtime raise workload, and
  workload above the safe level damages health. Workplace slots are visible at
  decision time. An unspecified workplace falls back to one with a free slot.
  A slot that fills while the agent travels fails the task with
  `workplace_full`.
- `eat` with no source picks the **nearest food source with stock**. This
  fixed agents starving beside an empty market.
- `offer_trade` with an empty `resource_offer` is a request for help.
  `accept_trade` re-checks both sides and swaps atomically.
- `steal` needs `social.allow_theft`. It may be detected or witnessed, which
  damages trust.

### Validation order (`engine/validation.py`)
Agent alive → action known/enabled → duration clamped → target resolution →
attached messages planned → **time** → **energy** → **tokens** → **attention**
→ action-specific constraints. Rejection reasons are stable strings
(`insufficient_tokens`, `food_out_of_stock`, `target_dead`, …), used in tests,
the decision log and the UI.

### Communication (`engine/communication.py`)
Messages cost tokens (base + per message token + distance + interference from
messages already sent this tick), time and energy. They arrive after
`delivery_delay_ticks`. The inbox is capped (oldest dropped) and unread
messages expire. An agent reads only up to `max_incoming_messages_processed_per_tick`
messages, and only while attention remains. Busy agents don't read. A "said"
message appears as a speech bubble on the map.

### Attention
Each decision has `attention_budget_per_tick`. The decision itself, extra
goals, pending offers, messages and observations all cost attention. Items
that don't fit are left out of the decision context.
`overload = (demand − budget)/budget` raises stress and suppresses existential
contemplation.

### Trust (`engine/trust.py`): directed Beta model
`trust = α/(α+β)` from a prior (`trusting` 4/1.5, `neutral` 2/2, `suspicious`
1.5/4 on the setup page). Only participants and witnesses update it. Positive
evidence: socialising, gifts, trades, help. Negative: refusals, unreliable
offers, theft (victim −1.0, witness −0.5). Evidence weight is capped, with
optional decay toward the prior. `Relationship` also tracks familiarity,
affinity, interaction counts, first and last contact.

### Personality drift (`engine/personality.py`)
Behaviour adds evidence (target, weight) per trait. Every
`update_interval_ticks`, each trait moves toward the weighted target by a
learning rate, with per-event change capped. Need-driven behaviour counts for
less (stealing while starving says less about criminal tendency).

### Existential goal (`engine/existential.py`)
At each decision opportunity:
`p = clamp(p_base + kS·spirituality + kN·novelty + kX·(0.6·stress+0.4·uncertainty) + kD·discussion + kF·free_attention − kO·overload)`,
sampled from the `existential` RNG stream. When active, the goal becomes
salient (it still competes with survival). Agents may reflect, discuss it or
record a **belief**; beliefs and revisions are logged. The map shows a violet
glow around agents with the goal active. It can be turned off on the setup
page.

### Death
Health ≤ 0 (cause = last damage: starvation, exhaustion, overwork, hazard), or
critical hunger for longer than `max_critical_hunger_ticks`. Death records the
cause, time, last actions and final state. Witnesses get a memory, stress and
uncertainty. Death is permanent unless `simulation.enable_replacement` is set.

### Economy and resource levels (`config/levels.py`)
The 7 levels, `very_scarce … very_abundant`, set food supply as a multiple of
population need (0.70× … 3.0×), meal price, wage, starting tokens, jobs per
agent and number of food sources. **They are scaled to the population**, so a
level means the same for 2 agents as for 20. In `load_config`, a
`resource_level` is applied after the preset, and explicitly set override
values still win.

### Setup page settings (`config/setup.py: SetupSettings`)
A friendly, bounded settings model (`extra="forbid"`) that
`settings_to_overrides()` maps onto the full config: name, population (2–50),
resource_level, personality_mode `identical|random`, personality_deviation
(0–0.5), personality_distribution `normal|uniform`, trait_means, days, seed,
world_size, communication_cost `free|cheap|normal|expensive`, trust_prior,
allow_theft, hazards `none|low|high`, replace_dead, existential_goal, provider
`none|mock|anthropic`, plus LLM fields. `/api/setup/preview` returns the
economy summary, warnings and the generated agents (with traits and `sprite`)
without creating a world.

### Rule policy (`engine/policy.py`)
A deterministic baseline. It is the fallback for every failed LLM decision and
the default "mind". It uses only what the agent knows and draws from the
`policy` RNG stream. It includes canned small talk and existential lines.

### Conversations
Messages are always one sender → one recipient. `analysis/conversations.py`
groups them into conversations: per-pair sessions split by pauses longer than
`gap_ticks` (a third of a day), merged into a **group** conversation when the
agents really talk together (a triangle A–B, A–C, B–C of overlapping sessions,
or one agent addressing several in the same tick). Talking to two people
separately stays two conversations. The engine records reads
(`TickResult.reads` → `messages.read_tick`), so a transcript shows each
message's status: `sending` (not delivered yet), `unread` (in the inbox),
`read`, `never_read` (expired or dropped: agents have limited attention) or
`undelivered` (recipient died). The transcript endpoint also returns the
sender's visible intention at that tick and the participants' socialise / gift /
trade / theft events. UI: `components/Conversations.tsx` (list + chat
transcript) in the World tab's right panel, plus the map focus mode.

### Measurement and experiments
- `analysis/behavior.py`: per-agent behaviour rates are correlated (Pearson)
  with **initial** traits under pre-registered trait→behaviour hypotheses,
  plus the full matrix. Shown in the Mind tab.
- `engine/metrics.py`: per-tick population metrics (alive, mean tokens, Gini,
  trust, happiness, …).
- `experiments/`: conditions × seeds runner, summary measures, mean ± 95% CI,
  Welch t-test against a baseline, CSV/JSON export, built-in templates. Each
  run is a normal persisted world tagged with the experiment. There is also a
  headless CLI: `python -m aisim.experiments`.

### Determinism
Every random process uses a **named seeded stream** (`engine/rng.py`: `init`,
`order`, `policy`, `existential`, `environment`, `social`). Stream state is in
the snapshot. Rule-based runs with the same seed and config are bit-for-bit
reproducible; LLM runs are not. **Never use `random`, `time` or unordered
iteration over sets inside the engine.**

---

## 3. Repository layout

```
CLAUDE.md                 this file
README.md                 user guide: run locally (run.sh / manual / Docker), features, credits
run.sh                    one-command launcher (venv, deps, UI build, start on :8000; --dev adds Vite :5173)
docker-compose.yml        PostgreSQL + backend + nginx frontend (port 8080)
docs/                     ARCHITECTURE, RULES, LLM, EXPERIMENTS, OPERATIONS, SECURITY
.github/workflows/ci.yml  backend pytest (SQLite + PostgreSQL) and frontend typecheck/test/build

backend/                  Python ≥3.11 package "aisim" (pyproject.toml)
  aisim/__main__.py       `python -m aisim`: loads .env (without overriding env), runs uvicorn
  aisim/engine/           AUTHORITATIVE simulation (no LLM imports!)
    state.py              Pydantic world state (WorldState, Agent, Location, Task, Message, TradeOffer, …)
    simulation.py         Simulation: begin_tick / apply_decisions / advance, needs, deaths, perception
    actions.py            ActionProposal, ActionSpec REGISTRY, per-action check/tick handlers
    validation.py         validate_action → ValidationResult (ordered checks, reason codes)
    policy.py             rule-based decision policy (also the fallback)
    social.py             socialize/give/trade/theft logic
    communication.py      message cost/time/delivery
    trust.py, personality.py, existential.py, goals.py, metrics.py, events.py
    worldgen.py           initial world and agents (names, backgrounds, locations, traits)
    rng.py                named seeded random streams, serialisable
  aisim/agents/           LLM decision service (no state mutation)
    service.py            LLMDecider: budgets, backpressure, concurrency, rate limit, timeout, fallbacks
    context.py            per-decision user message; enforces information boundaries and context budget
    prompt.py             system prompt (identical across agents/ticks → prompt-cached)
    schema.py             DecisionOutput (Pydantic) + JSON schema for structured output
    memory.py             memory retrieval scoring
  aisim/llm/              provider abstraction
    base.py               LLMRequest / LLMResponse / LLMError / LLMProvider protocol
    anthropic_provider.py Anthropic SDK (structured output, prompt caching, effort, server-side fallback)
    openrouter_provider.py OpenRouter chat completions over httpx (json_schema, exact cost from usage)
    claude_code_provider.py Claude subscription mode: runs the local `claude -p` CLI per decision
    credentials.py        per-world API keys (memory only) with environment-variable fallback
    mock_provider.py      offline provider (answers with the rule policy's choice; injectable failures)
    factory.py, pricing.py (USD per Mtok), ratelimit.py (token bucket)
  aisim/runtime/
    manager.py            WorldManager: create/load/restore/delete worlds, decider factory
    runner.py             WorldRunner: tick loop, pause/resume/speed, persistence retries, broadcast
    deciders.py           Decider protocol + RuleDecider
    hub.py                WebSocket fan-out (drops slow clients after 2 s)
    views.py              researcher views (world_view, agent_brief, agent_detail, tick_payload)
    appearance.py         agent → sprite sheet from its dominant starting trait
  aisim/api/
    app.py                create_app(): REST, WebSocket, setup endpoints, static SPA serving
    experiments.py        experiment endpoints (router)
    schemas.py, main.py   (main.py exposes `app` for uvicorn)
  aisim/persistence/      db.py, models.py (tables), repository.py, migrations/ (Alembic, inside the package)
  aisim/config/           schema.py (typed config), levels.py, setup.py, presets/*.yaml
  aisim/analysis/         behavior.py (trait ↔ behaviour)
  aisim/experiments/      spec, runner, service, stats, compare, templates, __main__ (CLI)
  scripts/stress_test.py  performance measurement
  tests/                  pytest suite (see §7)

frontend/                 React 18 + TypeScript + Vite + Mantine 7 + PixiJS 8 + Recharts
  public/sprites/         characters/*.png (18 sheets), environment/{dirt,grass1,grass2,tree}.png
  src/main.tsx            Mantine theme (teal, pixel font headings), fonts
  src/App.tsx             top-level: setup / worlds / experiments views, world tabs, roster, legend
  src/api.ts              typed REST client (+ optional bearer token from localStorage "aisim.apiToken")
  src/hooks/              useWorldStream (WebSocket + initial REST load, bounded histories)
  src/types.ts            TS mirrors of backend views; keep in sync with runtime/views.py
  src/theme.ts            mood/location/action colours, trustColor
  src/sprites.ts          sheet layout, animations, archetype labels, texture loading/cache
  src/terrain.ts          deterministic tile map (grass/dirt/paths/forests), night alpha
  src/props.ts            pixel-art buildings drawn with Graphics (workshop, market, camp, campfire)
  src/components/         WorldCanvas (Pixi map), AgentInspector, EventFeed, SocietyPanel, MindPanel,
                          Analytics, LLMPanel, ExperimentsPage, SetupPage, WorldControls, Avatar
  src/__tests__/          vitest unit tests
```

---

## 4. Backend technical details

### Config
- `load_config(preset, overrides)`: `default.yaml`, then the preset (presets
  only list differences), then overrides, then the resource level re-derived
  with explicit overrides re-applied. The result is validated into
  `SimulationConfig`.
- Every section model forbids unknown keys and has bounds. **A new config
  field needs a sensible default and bounds**, and a doc line in `docs/RULES.md`
  or `docs/LLM.md`.
- Presets: `default`, `scarcity`, `abundance`, `mock_llm`, `first_milestone_llm`.
- Each world stores its **fully resolved config**.

### Runtime and tick barrier
`WorldRunner.step()`: `begin_tick` → `await decider.decide(...)` (bounded by
`decision_timeout_seconds`) → `apply_decisions` → `advance` → persist (in a
worker thread, with retries) → publish to the Hub. The clock is decoupled from
LLM latency: late decisions get fallbacks. Pausing happens between ticks.
`speed` is ticks per second (0 means as fast as possible).

A database failure keeps the tick in memory, retries, then sets status `error`.
The next successful save flushes it. Statuses are
`paused | running | finished | error`.

### LLM decider (`agents/service.py`)
- Rule-controlled agents are decided immediately.
- LLM agents go through these checks in order:
  1. Spend caps (`world_budget_exhausted`, `agent_daily_budget_exhausted`).
  2. `max_queue_size` (`backpressure`).
  3. Semaphore (`max_concurrent_requests`) and the token-bucket rate limiter.
     If no slot frees up within half the decision window, the decision falls
     back immediately (`rate_limited`) rather than stalling the tick. The mock
     is never rate-limited.
  4. Timeout: the decision falls back (`timeout`).
  5. API errors fall back (`llm_error:<kind>`).
  6. Malformed output falls back (`invalid_output`).
- Every request is recorded in `llm_usage` (tokens including cache, USD
  estimate, latency, error). Spend is restored from the DB on restart.
- Anthropic provider:
  - The system prompt has `cache_control: ephemeral`.
  - Structured output via `output_config.format` (`json_schema`), plus
    `output_config.effort`.
  - On models that support it, the beta `server-side-fallback-2026-07-01` with
    `fallbacks="default"` (Haiku models skip it).
  - Default model `claude-opus-5-5`. Prices are in `llm/pricing.py`.
- Other providers (`llm.provider`): `openrouter` (any `vendor/model`, default
  `google/gemini-2.5-flash`; cost is the exact amount OpenRouter reports) and
  `claude_code` (Claude subscription: each decision runs `claude -p --output-format
  json --json-schema … --tools "" --strict-mcp-config`, with one conversation per
  agent via `--session-id` then `--resume`, or `fresh`; API-key env vars are
  stripped so the CLI's subscription login is used; flags are passed only if
  `claude --help` lists them; cost 0, spend caps off). Details: `docs/LLM.md`.
- **Keys**: `llm/credentials.py` resolves a key per world: a key typed on the
  setup page (memory only, set via `create_world(api_key=…)` or
  `POST /api/worlds/{id}/credentials`), else `ANTHROPIC_API_KEY` /
  `OPENROUTER_API_KEY`. Decider stats expose `credential`
  (`world|server|missing|subscription`) and `last_error_kind`; the LLM tab uses
  them to ask for a key after a restart. **Never store a key in the config or
  database, log it, return it from the API, or save it in the browser.**
  `/api/health` and `/api/setup/options` report only whether server keys exist.
  The CLI executable is chosen only by env vars (`AISIM_CLAUDE_PATH`, …), never by
  API input.
- `scripts/llm_smoke_test.py --provider openrouter|anthropic|claude_code|mock`
  runs a small chatty world with real LLM agents and prints decisions, messages,
  fallbacks and cost (keys come from the environment).

### Information boundaries (`agents/context.py`)
An agent's context contains only:
- its own state, memories, relationships and observations
- messages and offers it actually read this tick
- public facts about places (food stock only when nearby)
- other agents' *visible* behaviour (activity, apparent mood) within
  perception radius

Other agents' text is sanitised (control characters stripped, quotes
neutralised, length-limited) and quoted. The system prompt states that message
text is not an instruction. Sections fill in priority order within
`context_token_budget` (≈4 chars/token), with "(N omitted)" markers. A test
checks that a neighbour's private memory and token count never leak into a
context.

### Persistence
- SQLAlchemy 2 models (`persistence/models.py`):
  - `worlds`: metadata, resolved config, snapshot JSON, status, spend
  - `agents` and `relationships`: queryable mirrors, refreshed daily
  - per-tick append-only tables: `events`, `messages`, `decisions`,
    `memories`, `trust_changes`, `trait_history`, `metrics`, `llm_usage`
  - `experiments`
- A whole tick is written in one transaction. Snapshots are written every
  `snapshot_interval_ticks` (default 1; experiments use daily). The snapshot
  includes the RNG state.
- On restart, records newer than the last snapshot are **truncated**
  (`truncate_after`) so history matches state. Worlds come back paused unless
  `AISIM_AUTO_RESUME=true`.
- SQLite is the default (`sqlite:///./aisim.db`), with a write lock that
  serialises worker-thread writes. PostgreSQL uses `postgresql+psycopg://…`.
- **Alembic migrations live inside the package**
  (`aisim/persistence/migrations`: `0001_initial_schema.py`, `0002_message_read_tick.py`)
  so installed (non-editable) deployments still find them. They run at
  startup. For a schema change, add a new revision there and update
  `models.py`; never edit an existing revision.

### API (`api/app.py`, `api/experiments.py`)
REST under `/api`:
- `health`, `presets[/{id}]`, `catalog`
- `setup/options`, `setup/preview`, `setup/worlds`
- `worlds` (list/create), `worlds/{id}` (get/delete), `.../config`
- `.../start|pause|step|speed`
- `.../agents[/{aid}[/memories]]`, `.../events|messages|decisions|metrics|relationships|trust|traits|analysis|llm`
- `.../conversations[?agent=]` (threads) and `.../conversation?agents=a,b,…` (transcript), see below
- `.../credentials` (POST a provider key for that world; memory only)
- `experiment-templates`, `experiments[/{id}[/cancel|/export]]`

Mutating endpoints need `Authorization: Bearer` only when `AISIM_API_TOKEN` is
set. The step endpoint stops a long multi-tick request if the client
disconnects.

WebSocket `/ws/worlds/{id}`:
- On connect the server sends `{"type":"snapshot","world":…}`.
- Each tick it sends `{"type":"tick","world","metrics","events","messages","decisions"}`.
- Status changes send `{"type":"status","world"}`.
- The client sends `"ping"` and gets `{"type":"pong"}`.

`world` is `runtime/views.world_view`. Each agent brief includes `sprite`,
`said`, `intention`, `existential_active` and `traveling`.

Static UI: if `frontend/dist` exists (or `AISIM_STATIC_DIR`), the backend
serves it at `/` with an SPA fallback and a path-traversal check. So
`python -m aisim` serves the whole app on port 8000.

Environment variables: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`,
`AISIM_CLAUDE_PATH`, `AISIM_CLAUDE_WORKDIR`, `AISIM_CLAUDE_EXTRA_ARGS`, `AISIM_AUTO_RESUME`, `AISIM_API_TOKEN`, `AISIM_CORS_ORIGINS`, `HOST`, `PORT`,
`LOG_LEVEL`, `AISIM_STATIC_DIR`. `.env` is read from the CWD or `backend/`.
Uvicorn graceful shutdown is capped at 5 s.

---

## 5. Frontend technical details

- **Pinned versions**: React 18.3.1, Mantine 7.15.2, PixiJS **8.6.6**,
  Recharts 2.15.0, Vite 6.0.7, TS 5.7.3, vitest 2.1.8,
  @fontsource/pixelify-sans 5.1.0. `npm run build` runs `tsc -b && vite build`.
  The Vite dev server proxies `/api` and `/ws` to `AISIM_BACKEND`
  (default `http://127.0.0.1:8000`).
- **Navigation** is hash-based:
  - `#setup` (default when no world) shows the setup page
  - `#experiments` shows the experiments page
  - `#<worldId>` opens a world; the last world is remembered in localStorage
  - World tabs: World, Society, Mind, Analytics, LLM usage
- `types.ts` mirrors backend views by hand. **When you change a view in
  `runtime/views.py`, update `types.ts`.**

### The pixel-art map (`components/WorldCanvas.tsx`)
- **Sprite pack** ("Puny Characters"): character sheets are **768×256 = 24
  columns × 8 rows of 32×32 frames**.
  - Rows are facing directions clockwise from south: S, SE, E, NE, N, NW, W,
    SW.
  - Columns: 0 stand, 1–4 walk, 5–8 swing (7 has the slash arc), 9–12 bow,
    13–15 raise/throw, 20 hit flash, 23 lying down.
  - Feet are at y = 23 of the frame (sprite anchor `(0.5, 23/32)`). The
    visible character occupies about (7..25, 6..24) of the frame, which is
    what `Avatar.tsx` and the SVG crop in `SocietyPanel` use.
  - Environment tiles are 16×16: dirt, grass1, grass2, tree. Sheet names are
    lowercase (`mage-red`, `human-worker-cyan`, `orc-peon-red`, …;
    `CHARACTER_SHEETS` in `sprites.ts`).
- **Facing**: `directionRow(dx, dy)` uses
  `octant = round(atan2(dy,dx)/(π/4)) mod 8`, then `row = (2 − octant) mod 8`.
- **Animations** (`ANIMS`, `animFor`):
  - dead → lie
  - moving → walk
  - work → tool swing (frames 5, 6, 8, 6; no slash arc)
  - steal → sword swing
  - create / study → raise
  - rest → lie
  - otherwise → stand
  - A health drop of more than 3 → brief hurt flash.
- **Appearance** (backend `runtime/appearance.py`): the sheet comes from the
  strongest *starting* trait if it is ≥ 0.08 above 0.5.
  - The mapping is in `TRAIT_ARCHETYPE`: mage, archer, warrior, soldier,
    villager, guard, orc (criminal_tendency only).
  - Otherwise the sheet is a deterministic sha256 pick from the human pool,
    never orcs.
  - Frontend labels are in `ARCHETYPE_LABELS`. **If you add a trait, map it in
    `appearance.py`.** A test checks every sheet file exists.
- **Units**: `UNIT = 8` screen px per world unit at scale 1, and one 16 px tile
  is 2 world units (`terrain.ts`).
- **Terrain** is deterministic from world id + locations:
  - grass variants from value noise
  - ragged dirt clearings under locations
  - winding paths along a Prim minimum spanning tree between locations
  - trees thicker at the edges and in noise clusters, kept off paths and
    places
  - The ground is baked into one `RenderTexture` via
    `app.renderer.render({container, target})`. Pixi 8.6 has no
    `cacheAsTexture`.
- **Props** (`props.ts`): buildings are drawn with `Graphics` because the pack
  has no buildings.
  - workplace → workshop with chimney and lit windows
  - food → market stall whose produce reflects stock
  - rest → tents
  - gathering → campfire with an animated flame
  - Buildings use `zIndex = cy − 48`, so agents anywhere in the clearing draw in front.
- **Scene graph**:
  - `root` (camera; world px) holds the ground sprite, `objects` (sortable by
    y: trees, props, agents), the darkness layer and additive lights.
  - `overlay` is in screen space: location labels, agent labels (name, ◆ for
    LLM agents, mood dot, health bar, action emote) and bubbles. Text stays
    crisp at any zoom.
- **Camera**: `fit` is the scale where the whole map is visible; `zoom` is
  relative to fit (1–8).
  - The initial view frames the living agents (`frameVillagers`, max 2.5×).
  - ⤢ shows the whole map, ◎ follows the selected agent.
  - Drag to pan, wheel to zoom around the cursor.
- **Crowds and bubbles**: agents in the same 2.5-unit cell fan out in an arc
  in front of the spot (`crowdOffset`, visual only). Speech bubbles (parchment)
  and thought bubbles (violet; Intentions Off/Selected/All) are separated
  greedily (`separateBubbles`). Above 40 agents only the selected agent's
  label shows.
- **Conversation focus**: `focus` (participant ids) highlights them with a teal
  ring, dims everyone else (alpha 0.3, no labels or bubbles), frames them once
  and then follows their centroid (`followGroup`; dragging stops it, the ◎ in
  the focus chip resumes). Each new message (`said` + `said_to` in the agent
  brief) spawns an envelope that flies sender → recipient (`animateEnvelopes`);
  with a focus, only messages among the participants do.
- **Day/night**: `nightAlpha(tick, ticksPerDay)` is 0 from 07:00 to 18:00,
  ramps at dusk and dawn, and is 0.5 at night. Lights fade in with it.
- Pixi details that bit before:
  - set `texture.source.scaleMode = 'nearest'` for pixel art
  - `antialias: false`, `roundPixels: true`
  - frame textures are cached (`frameTexture`)
  - compare against `Texture.EMPTY` before destroying old textures
- Mantine gotcha: the `Slider` accessibility label goes in `thumbLabel`, not
  `aria-label`.

---

## 6. Running and developing

```bash
./run.sh                 # installs if needed, builds UI, serves everything on http://localhost:8000
./run.sh --dev           # + Vite hot reload on http://localhost:5173

# manual
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
python -m aisim                                   # API (+ built UI) on :8000
cd frontend && npm ci && npm run dev              # UI dev server on :5173 (proxies to :8000)
```

LLM agents: on the setup page pick **LLM provider API key** (OpenRouter or
Anthropic; paste a key or rely on the server's env var) or **Claude
subscription** (needs Claude Code installed and signed in on the backend's
machine). "Mock LLM" runs the whole LLM pipeline offline for free. Never commit
keys; the user has given test keys in chat before; use them only via environment
variables.

- In the cloud container, the `claude` CLI belongs to the hosted session itself,
  not to the user's subscription: don't run real subscription-mode calls there.
  Test with `tests/fixtures/fake_claude.py` (`AISIM_CLAUDE_PATH`), which mimics
  the CLI's JSON output and session errors. Network egress may block
  openrouter.ai (the user can allow it in the environment's network settings).

### Working in a cloud container (as previous agents did)
- The container has no public address, so the user can't open your localhost.
  Verify UI work yourself with headless Chromium/Playwright and look at the
  screenshots. Launch flags: `--use-gl=swiftshader --enable-unsafe-swiftshader`
  for WebGL. Wait about 3–5 s after `networkidle` for Pixi to load textures.
  Software-WebGL "GPU stall" console warnings are harmless.
- PostgreSQL may need `service postgresql start` after a container restart.
  SQLite needs nothing.
- `pkill -f <pattern>` / `pgrep -f` can match your own shell command line and
  kill it (exit code 144). Run kills in a separate command, or use a `[x]`
  regex trick.
- Don't name scratch scripts after stdlib modules (e.g. `bisect.py`).

---

## 7. Tests and CI

```bash
cd backend && pytest -q                     # ~161 passed, 5 skipped (live LLM tests skip without a key)
TEST_DATABASE_URL=postgresql+psycopg://… pytest -q tests/test_api_persistence.py tests/test_experiments.py
ANTHROPIC_API_KEY=… pytest -m live_llm tests/test_llm_live.py   # real API, costs money
cd frontend && npm run typecheck && npm test && npm run build
```

- Backend tests: `test_engine_rules` (needs, actions, validation, death,
  determinism), `test_social_and_models`, `test_llm_decisions` (offline LLM
  pipeline: schema, budgets, timeouts, boundaries, request shape),
  `test_api_persistence` (API, WS, restore/truncate), `test_experiments`,
  `test_analysis`, `test_setup`, `test_appearance`, `test_providers` (OpenRouter via a mock transport, Claude CLI via `tests/fixtures/fake_claude.py`, key handling), `test_llm_live` (marked
  `live_llm`).
- `tests/conftest.py` has helpers: `make_sim(overrides)`, `place(sim, agent,
  type)`, `run_action(sim, agent_id, proposal)` for single-tick rule tests.
- Frontend tests are in `src/__tests__/` (trust colours, CSV export,
  sprite facing and animations, deterministic terrain).
- CI (`.github/workflows/ci.yml`) runs backend pytest on Python 3.12 with
  SQLite and PostgreSQL 16, and frontend typecheck, test and build on Node
  22. Keep it green. Run the same commands locally before pushing.

---

## 8. Invariants and checklists

- **Engine purity**: no LLM, network, wall-clock or global `random` in
  `aisim/engine`. All randomness goes through named streams.
- **Agents propose, the engine validates**: new behaviour means a new or
  changed `ActionSpec` plus validation, never a shortcut from the LLM layer
  into state.
- **Information boundaries**: anything new added to an agent's context must be
  something that agent could know. Extend the leak test if you add
  sensitive data.
- **Secrets**: the API key stays in the backend environment and is never
  logged, stored or returned.
- **Determinism tests**: a change that alters RNG draw order changes seeded
  outcomes. That is fine if intended, but update the expectations deliberately.
- **Adding a trait**: `TRAITS` + `TRAIT_DESCRIPTIONS` (state.py), the
  existential/goal/policy uses if relevant, the behaviour hypotheses
  (analysis) and `TRAIT_ARCHETYPE` (appearance.py). The frontend gets trait
  names from the API (`/api/setup/options`, `trait_descriptions`), so it needs
  no change.
- **Adding an action**: register it in `actions.py`, add rule-policy use if
  needed, an emote in `ACTION_EMOTES`, an animation in `animFor`, colours in
  `theme.ts`, a row in `docs/RULES.md`, and tests.
- **Adding a location type**: worldgen, a prop in `props.ts` (`buildProp`),
  label details in `WorldCanvas.update`, and `LOCATION_COLORS/ICONS`.
- **Schema changes**: a new Alembic revision in the package, plus the
  repository and views as needed.
- **Docs**: keep `README.md` (user-facing), `docs/*.md` and this file current
  when behaviour changes.

---

## 9. Known limitations and ideas for next steps

- Perception, meetings and social metrics are O(n²). Fine for a few hundred
  agents; a spatial grid is the next optimisation. Snapshots grow with
  memories × agents and relationships (n²). Raise `snapshot_interval_ticks`
  for big worlds. Measured numbers are in `docs/OPERATIONS.md`.
- LLM runs aren't reproducible (model output varies); use several seeds.
- **Asset licence**: the sprite pack came from the user as a zip with no
  licence file. The README credits it as "Puny Characters" by Shade and asks
  readers to check the licence before redistributing. Confirm with the user
  before publishing the repo.
- The original spec isn't in the repo (see §1). Ask the user for it if you
  need to check a numbered requirement.
- Possible UI follow-ups: a minimap, sprite-based building art if the user
  supplies building tiles, bow animation (cols 9–12, currently unused),
  per-location ambient animation.

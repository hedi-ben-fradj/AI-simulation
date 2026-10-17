# Architecture

```
┌──────────────────────── frontend (React + PixiJS) ────────────────────────┐
│ World map · inspector · events · Society · Mind · Analytics · LLM · Exps  │
└───────────────┬───────────────────────────────────────▲──────────────────┘
          REST /api/*                             WebSocket /ws/worlds/{id}
┌───────────────▼──────────── backend (FastAPI) ─────────┴──────────────────┐
│ api/            HTTP + WS endpoints (typed request schemas, optional token)│
│ runtime/        WorldManager → WorldRunner per world (tick loop, pause,    │
│                 speed, persistence retries, broadcast via Hub)             │
│ agents/         LLMDecider: context builder, prompt, memory retrieval,     │
│                 schema validation, budgets, rate limit, timeouts           │
│ llm/            Provider interface: Anthropic, mock; pricing; rate limiter │
│ engine/         AUTHORITATIVE simulation: state, actions, validation,      │
│                 needs, death, communication, trust, personality,           │
│                 existential goal, goals, rule policy, metrics              │
│ analysis/       trait ↔ behaviour measurement                              │
│ experiments/    conditions × seeds runner, statistics, exports, CLI        │
│ persistence/    SQLAlchemy models, Alembic migrations, Repository          │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │
                            PostgreSQL (or SQLite)
```

## The one rule

**The LLM proposes; the engine decides.** `aisim.engine` never imports `aisim.llm`
or `aisim.agents`. Agents (rule-based or LLM) return an `ActionProposal`; the
engine validates it against the *current* state (`validation.py`) and applies the
deterministic consequences (`actions.py`, `social.py`, `simulation.py`).

## A tick

```
WorldRunner.step()
  ├─ sim.begin_tick()            deliver messages, expire offers, allocate attention,
  │                              sample existential activation → DecisionRequest[]
  ├─ decider.decide(requests)    rule policy / LLM calls in parallel, bounded window
  ├─ sim.apply_decisions()       validate each proposal; fallback for missing/invalid
  ├─ sim.advance()               run tasks, needs, deaths, perception, daily rules,
  │                              personality updates, metrics → TickResult
  ├─ repo.save_tick()            one DB transaction (events, messages, decisions,
  │                              memories, trust/trait changes, metrics, LLM usage,
  │                              periodic snapshot)
  └─ hub.publish()               WebSocket tick payload to subscribed browsers
```

A slow model never blocks the world: after `decision_timeout_seconds` pending
requests are cancelled and those agents get the rule-based fallback. Pausing takes
effect between ticks, so state is never persisted mid-tick.

## State and persistence

* World state is a tree of Pydantic models (`engine/state.py`). A snapshot is the
  JSON dump of that tree **including the state of every named random stream**, so a
  restored world continues exactly where it stopped.
* Snapshots are written every `snapshot_interval_ticks` (default 1). Per-tick
  records (events, messages, decisions, memories, trust and trait changes, metrics,
  LLM usage) are append-only tables. If the backend restarts after a tick that was
  not snapshotted, records newer than the snapshot are truncated before resuming,
  so history and state never disagree.
* `agents` and `relationships` tables are a queryable mirror refreshed daily; live
  views read the in-memory state.
* If a database write fails, the runner keeps the tick in memory, retries, and
  pauses the world with status `error`; the next successful save flushes it.

## Information boundaries

| Data | Who can see it |
|---|---|
| An agent's memories, resources, emotions, beliefs, trust values | that agent (and the researcher UI) |
| Public events (work, eating, death, theft if noticed, reflection…) | agents within `perception_radius` |
| Private events (messages, trade offers, refusals) | participants |
| Other agents' visible activity and apparent mood | agents within perception radius |
| Food stock at a location | agents within perception radius; price is public |

The researcher UI is an observation tool and shows everything; agent prompts are
built only by `agents/context.py`, which enforces the table above.

## Extending

* **New action:** register an `ActionSpec` (preconditions in `check`, per-tick
  effects in `tick`, costs, duration limits). It automatically appears in prompts,
  the output schema and the UI catalogue.
* **New model provider:** implement `LLMProvider.complete(LLMRequest) → LLMResponse`
  and add it to `llm/factory.py`.
* **Distributed workers:** the runtime only depends on the `Decider` protocol
  (`runtime/deciders.py`). A Redis-backed queue with external workers can replace
  the in-process asyncio pool without touching the engine.
* **Schema change:** edit `persistence/models.py`, then
  `alembic revision --autogenerate -m "..."` in `backend/`.

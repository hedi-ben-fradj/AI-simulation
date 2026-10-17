# Deployment and Operations

## Docker Compose (recommended)

```bash
ANTHROPIC_API_KEY=sk-ant-...  docker compose up --build     # key optional
open http://localhost:8080
```

Services: `db` (PostgreSQL 16, volume `pgdata`), `backend` (FastAPI on :8000,
runs migrations at startup), `frontend` (nginx serving the build and proxying
`/api` and `/ws` to the backend). Only the frontend port is published.

## Manual setup

```bash
# PostgreSQL
createuser -P aisim && createdb -O aisim aisim

# Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://aisim:aisim@localhost:5432/aisim
export ANTHROPIC_API_KEY=sk-ant-...          # only needed for LLM agents
python -m aisim                              # HOST/PORT/LOG_LEVEL honoured

# Frontend
cd frontend && npm ci && npm run dev         # dev server on :5173
npm run build                                # static files in dist/ (serve behind a proxy like nginx.conf)
```

## Configuration (environment)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./aisim.db` | SQLAlchemy URL; use PostgreSQL (`postgresql+psycopg://…`) for real use |
| `ANTHROPIC_API_KEY` | – | backend only; required for `llm.provider: anthropic` |
| `AISIM_AUTO_RESUME` | `false` | restart worlds that were running at shutdown |
| `AISIM_API_TOKEN` | – | if set, mutating API calls require `Authorization: Bearer <token>` (the UI stores it in localStorage under `aisim.apiToken`) |
| `AISIM_CORS_ORIGINS` | `*` | comma-separated allowed origins |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | bind address |
| `LOG_LEVEL` | `INFO` | `DEBUG` logs every tick; slow ticks (>10 s) log a warning |

Simulation parameters live in YAML presets (`backend/aisim/config/presets/`) and
per-world overrides; see `docs/RULES.md` and `docs/LLM.md`.

## Tests

```bash
cd backend && pytest -q                                   # unit + integration (SQLite)
TEST_DATABASE_URL=postgresql+psycopg://… pytest -q tests/test_api_persistence.py tests/test_experiments.py
ANTHROPIC_API_KEY=… pytest -m live_llm tests/test_llm_live.py   # real API, costs money
cd frontend && npm run typecheck && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs all of the above except the live LLM suite.

## Restart and recovery

* On startup every saved world is restored from its last snapshot (paused unless
  `AISIM_AUTO_RESUME=true` and it was running). Per-tick records newer than the
  snapshot are removed so history matches state.
* A graceful shutdown pauses each world after its current tick.
* Experiments running at shutdown are marked `interrupted`; completed runs keep their worlds.
* Database outage: the running world retries the write, then pauses with status
  `error` keeping the tick in memory; press **Resume** when the database is back.
* LLM outage: affected agents fall back to the rule policy each tick
  (`llm_error:<kind>` in the decision log); the world keeps running.

## Performance

Measured with `python scripts/stress_test.py` (single core, PostgreSQL on the same
host, abundance preset, 24 ticks):

| Agents | Engine ms/tick | Mock-LLM pipeline ms/tick | Save ms/tick (snapshot every tick) | Save ms/tick (daily snapshot) |
|---:|---:|---:|---:|---:|
| 10 | 1 | 3 | 24 | 13 |
| 50 | 12 | 33 | 144 | 42 |
| 100 | 53 | 102 | 449 | 105 |
| 200 | 341 | 519 | 1396 | 420 |

Known bottlenecks and levers:

* **Perception and relationships are O(n²)** (meeting detection, observation
  propagation, social-network metrics). Fine up to a few hundred agents; a spatial
  grid would be the next optimisation.
* **Snapshots grow with memories × agents and relationships (n²).** For large
  worlds set `simulation.snapshot_interval_ticks` to e.g. 6–24 (experiments already
  snapshot daily). The cost is replaying at most that many ticks of history after
  a crash (they are truncated, not lost silently).
* **Real LLM latency dominates LLM worlds** (seconds per call). Throughput is
  governed by `llm.max_concurrent_requests`, `requests_per_minute`, provider rate
  limits and `decision_timeout_seconds`; multi-tick tasks reduce calls per agent.
  `max_queue_size` caps LLM calls per tick (excess agents use the rule policy).
* **Cost**: each LLM decision sends ~1–2k context tokens plus a ~1k-token system
  prompt that is prompt-cached across agents and ticks. Spend caps (`maximum_world_spend`,
  `maximum_agent_daily_spend`, experiment `maximum_total_spend`) are enforced
  before each call.
* The frontend renders with PixiJS; above 40 agents labels are shown only for the
  selected agent. Event/message histories in the browser are bounded.

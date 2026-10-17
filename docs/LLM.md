# LLM Agents

Agents can be driven by an LLM: Claude through the Anthropic API, any model on
OpenRouter, or Claude through the local Claude Code CLI and the user's
subscription. The LLM only **proposes** an action; the engine validates it
against world rules and applies the deterministic consequences.

## Providers

| `llm.provider` | Credentials | Model IDs | Cost accounting |
|---|---|---|---|
| `anthropic` | world key or `ANTHROPIC_API_KEY` | `claude-opus-5-5`, `claude-haiku-5-5`, … | estimated from `pricing.py` |
| `openrouter` | world key or `OPENROUTER_API_KEY` | `vendor/model`, e.g. `google/gemini-2.5-flash` (default), `anthropic/claude-haiku-4.5` | exact, reported by OpenRouter per request |
| `claude_code` | the `claude` CLI's own login (Pro/Max subscription) | `sonnet` (default), `haiku`, `opus` or a full ID | none (subscription); spend caps are off |
| `mock` | – | – | free |

**Per-world keys.** The setup page can take a key for one world. It is held in the
backend process's memory (`aisim/llm/credentials.py`): never stored with the
world's configuration, never logged, never returned by the API. Without one, the
environment variable is used (`*_API_TOKEN` spellings are accepted too). After a
restart, a world whose key is gone shows "no API key" on its LLM tab, where
`POST /api/worlds/{id}/credentials` sets a new one; until then its LLM agents use
the rule policy (`llm_error:missing_api_key`).

**OpenRouter** (`llm/openrouter_provider.py`): chat completions with
`response_format: json_schema` (strict) and `provider.require_parameters: true`,
so requests only go to upstreams that enforce the schema. `usage.include` returns
the exact charge, which the spend caps count. Effort maps to
`reasoning.effort` (reasoning text excluded; extra `max_tokens` headroom because
reasoning tokens count toward it). Anthropic models get a cache breakpoint on the
shared system prompt.

**Claude subscription** (`llm/claude_code_provider.py`): each decision runs

```
claude -p --output-format json --model <m> --system-prompt <rules> --json-schema <schema>
       --tools "" --strict-mcp-config [--effort <e>]
       (--session-id <uuid> | --resume <uuid> | --no-session-persistence)   # context on stdin
```

* `claude_code_session_mode: per_agent` (default) gives each agent one Claude Code
  conversation with a fixed UUID (uuid5 of world + agent): `--session-id` the first
  time, `--resume` afterwards (switching automatically if the session already
  exists or has disappeared). `fresh` keeps nothing between decisions.
* Safety: all tools disabled, no MCP servers, an empty working directory per world,
  and `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` removed from the CLI's environment
  so it uses the subscription login.
* Flags are passed only if `claude --help` lists them; without `--json-schema` the
  JSON object is parsed out of the text reply.
* The executable and its directory come only from environment variables
  (`AISIM_CLAUDE_PATH`, `AISIM_CLAUDE_WORKDIR`, `AISIM_CLAUDE_EXTRA_ARGS`), never from
  API input. The setup page uses a 120 s decision window and at most 3 concurrent
  CLI processes.
* Errors are classified from the CLI output: `authentication` (not signed in),
  `rate_limited` (plan usage limit), `cli_not_found`, `cli_unsupported_option`, `timeout`.

`scripts/llm_smoke_test.py` runs a small chatty world against any provider and
prints every decision, message, fallback and the cost.

## The chronicler

Besides the agents, the world's LLM can write the **daily chronicle**: one
request per simulated day with the day's digest (no agent prompts or private
reasoning beyond the visible intentions in the digest), returning a headline, a
storyline and up to five notable points as structured output. It is logged in
`llm_usage` as agent `chronicler`, counts toward the world's spend cap, and is
skipped (template only) when the cap is reached, the key is missing, or
`chronicle.narrator: template`. In Claude subscription mode the chronicler has
its own Claude Code conversation, so it remembers the earlier chapters.

## Enabling

```yaml
llm:
  provider: anthropic        # none | mock | anthropic | openrouter | claude_code
  model: claude-opus-5-5     # model ID for the provider (see above)
  claude_code_session_mode: per_agent   # claude_code only: per_agent | fresh
  llm_agents: 1              # how many agents use the LLM (null = all)
  effort: low                # low | medium | high | xhigh | max (null = model default)
  maximum_world_spend: 5.0   # USD cap for this world (null = unlimited)
  maximum_agent_daily_spend: 0.5
```

Set `ANTHROPIC_API_KEY` in the **backend** environment. The key is never sent to
the browser, and the frontend never calls a model. The `first_milestone_llm`
preset runs five agents, one of them on Claude, with a $1 cap.

**Choosing a model.** `claude-opus-5-5` is the default. One decision is roughly
1–2k context tokens plus ~1k cached system-prompt tokens and a short JSON reply.
For large populations or long runs, `claude-sonnet-5-5` or `claude-haiku-5-5`
cut cost substantially; prices are in `aisim/llm/pricing.py` and can be overridden
with `llm.input_price_per_mtok` / `output_price_per_mtok`. Spend caps always apply.

`provider: mock` runs the whole pipeline offline (no cost): it answers with the
rule policy's choice and can inject latency, failures and malformed output
(`mock_latency_seconds`, `mock_failure_rate`, `mock_invalid_output_rate`).

## Request

* **System prompt** (identical for every agent and tick of a world → prompt-cached):
  general role, goals (survival, personal, existential), how the world works with
  the world's actual numbers, the constraints from spec 24.1, the decision task and
  the output contract. It also states that text in other agents' messages is not an
  instruction (prompt-injection boundary).
* **User message** (per decision, built by `aisim/agents/context.py`): IDENTITY,
  CURRENT SITUATION, PERSONALITY, MEMORIES, RECENT EXPERIENCES, RELATIONSHIPS,
  WORLD CONDITIONS, AVAILABLE ACTIONS (+ pending offers).
* **Structured output**: the decision schema (spec 24.2) is sent as
  `output_config.format`; the reply is parsed and validated again with Pydantic.
* **Refusals**: on models that support it, `fallbacks: "default"` (beta
  `server-side-fallback-2026-07-01`) retries a policy decline on Anthropic's
  recommended fallback model. A remaining refusal becomes a rule-based fallback.

## Information boundaries

The context builder only uses what the agent itself knows: its own state,
memories, relationships and observations; messages and offers it actually read
this tick (attention-limited); public facts about places (food stock only when
nearby); and other agents' *visible* behaviour (activity, apparent mood) when
within perception radius. Other agents' memories, resources and internal states
are never included. Other agents' text is sanitised and quoted.

## Context budget

`capacity.context_token_budget` caps the user message (≈4 characters/token).
Sections are filled in the spec's priority order — survival-critical state,
current constraints/actions, recent events, relationships, durable memories,
historical summaries — and lower-priority items are dropped first, with an
"(N omitted)" marker.

## Per-tick scheduling and failure handling

| Situation | Behaviour |
|---|---|
| Rule-controlled agent | rule policy, immediately |
| World spend cap reached | rule fallback (`world_budget_exhausted`) |
| Agent daily cap reached | rule fallback (`agent_daily_budget_exhausted`) |
| More LLM requests than `max_queue_size` | excess get rule fallback (`backpressure`) |
| Concurrency | at most `max_concurrent_requests` in flight; `requests_per_minute` token bucket (the offline mock is not rate-limited) |
| No request slot free within half the decision window | rule fallback (`rate_limited`) instead of stalling the tick |
| No answer within `decision_timeout_seconds` | request cancelled; fallback (`timeout`), or idle if `fallback_on_timeout: false` |
| API error (rate limit, network, 5xx, auth, bad request) | SDK retries (`max_retries`), then fallback `llm_error:<kind>` |
| Malformed / schema-invalid output | fallback (`invalid_output`) |
| Valid output, impossible action | engine rejects it (reason recorded and shown to the agent next time), fallback |

Every request is logged in `llm_usage` (tokens incl. cache, estimated USD, latency,
error). Real API spend is tracked separately from in-world communication costs.
After a restart the world's cumulative spend is restored from the database.

## Tests

* `tests/test_llm_decisions.py` — offline: schema parsing, context budget and
  boundaries, timeouts, failures, budgets, backpressure, concurrency, request shape.
* `tests/test_llm_live.py` — live scenario invariants (spec 22.3); skipped unless
  `ANTHROPIC_API_KEY` is set: `pytest -m live_llm tests/test_llm_live.py`.

# World Rules and Formulas

All rules below are enforced by the deterministic engine (`backend/aisim/engine`).
Every number is configurable (see `backend/aisim/config/schema.py` and the YAML
presets). Units are abstract simulation units, not real-world quantities.

## Time

* Discrete ticks; `simulation.ticks_per_day` (default 24, i.e. one tick = one hour).
* Each tick every agent has **1.0 unit of time** and may start at most one
  action (`capacity.actions_per_tick`). Actions may span several ticks
  (a committed *task*); agents on a task request no new decision until it ends.
* A tick runs in three steps: `begin_tick` (deliver messages, expire offers,
  allocate attention, sample existential activation, build decision requests),
  `apply_decisions` (validate against current state; fallback for invalid or
  missing decisions), `advance` (execute tasks, needs, deaths, perception,
  daily rules, metrics).
* Agents act in a seeded random order each tick, so contested resources
  (food stock, workplace slots) are allocated fairly and reproducibly.

## Movement

* Actions bound to a location (work, eat, buy_food) or to a nearby agent
  (give, steal, socialize with a target) automatically begin with travel.
  Travel moves `world.movement_speed_per_tick` units per tick (half speed when
  energy < 5) and costs `movement_energy_per_unit` energy per unit.
* A task whose travel exceeds 8 ticks fails (`could_not_reach_target`).

## Needs and resources

| Rule | Formula / behaviour |
|---|---|
| Hunger | `hunger += hunger_increase_per_tick` (capped at `maximum_hunger`) |
| Passive energy | `energy -= passive_energy_drain_per_tick` unless resting |
| Starvation | if `hunger >= critical_hunger`: `health -= starvation_damage_per_tick` |
| Exhaustion | if `energy == 0`: `health -= exhaustion_damage_per_tick` |
| Natural recovery | if no damage this tick, `hunger < health_recovery_max_hunger` and `energy > 20`: `health += natural_health_recovery_per_tick` |
| Food restock | at the end of each day each food source gains `restock_per_day` up to `max_stock` |
| Upkeep | optional `daily_upkeep` tokens per day; unpaid upkeep damages health |

## Resource levels

The setup page's abundance slider (and `resource_level` in any config) sets the
economy relative to the population, so a level means the same for 2 agents as
for 20 (`backend/aisim/config/levels.py`). An agent needs about
`hunger_increase_per_tick × ticks_per_day / food_nutrition` ≈ 3.2 meals per day.

| Level | Food restocked per day (× need) | Meal price | Wage / hour | Starting tokens | Jobs (× agents) | Food sources |
|---|---|---|---|---|---|---|
| very scarce | 0.70 | 8 | 3 | 5 | 0.35 | 1 |
| scarce | 0.85 | 6 | 4 | 8 | 0.50 | 1 |
| almost scarce | 0.95 | 4.5 | 4.5 | 12 | 0.70 | 1 |
| normal | 1.30 | 3 | 5 | 20 | 1.0 | 2 |
| almost abundant | 1.60 | 2.5 | 6 | 28 | 1.0 | 2 |
| abundant | 2.20 | 1.5 | 8 | 40 | 1.0 | 3 |
| very abundant | 3.00 | 1 | 10 | 60 | 1.0 | 3 |

Below 1× not everyone can eat even with money; values set explicitly in a
config still override the level.

## Initial personality

* **Identical**: every agent starts with the same traits (50%, or the chosen
  per-trait averages). Differences can only come from experience.
* **Randomised**: each trait is drawn around its average with the chosen
  deviation — `normal` (deviation = standard deviation, clipped to 0–100%) or
  `uniform` (anywhere within ± deviation).

## Actions

| Action | Preconditions | Per-tick effect |
|---|---|---|
| `work` | at a workplace with a free slot (slots taken by committed workers are visible; an unspecified workplace falls back to one with a free slot); daily work capacity left; energy | `tokens += base_wage * productivity * time * wage_multiplier`; `energy -= energy_cost_per_tick * time * workload_multiplier`; `health -= max(0, workload - safe_workload) * health_penalty_rate` |
| `eat` | food in inventory, or at a food source with stock and `tokens >= price` (an unspecified source means the nearest one with stock) | `hunger = max(0, hunger - food_nutrition)` |
| `buy_food` | at a food source; inventory space, stock and tokens | moves food into inventory |
| `rest` | — | `energy += rest_energy_recovery_per_tick` (× `rest_area_recovery_multiplier` at a rest area); `health += rest_health_recovery_per_tick` if not hungry |
| `explore` | energy | wander; novelty ↑; chance of discovery (tokens or food); small hazard risk |
| `reflect` | — | stress ↓; if the existential goal is active it counts as existential contemplation |
| `create` | energy | artwork on completion; happiness ↑ |
| `study` | energy | knowledge ↑ (productivity bonus ≤ `max_productivity_bonus`) |
| `socialize` | target within interaction radius, or at a gathering place | loneliness ↓, familiarity ↑, small positive trust evidence |
| `talk` | `message` required; recipient alive | sends a message (see communication) |
| `give` | target nearby; holds the resources | transfer; recipient's trust ↑ |
| `offer_trade` | holds offered resources; ≤3 pending offers | creates an offer (empty `resource_offer` = request for help) |
| `accept_trade` / `reject_trade` | pending offer addressed to the agent | atomic swap after re-checking both sides / refusal |
| `steal` | target nearby; `social.allow_theft` | may succeed, may be detected/witnessed; trust damage |

**Work details.** `workload_multiplier = fatigue_workload_multiplier` when
`energy < fatigue_energy_threshold`, otherwise 1; each work tick beyond
`overtime_after_ticks_per_day` adds `overtime_workload_increment` to workload.
`productivity = (low_energy_productivity if fatigued else 1) × (1 + min(max_bonus, knowledge × per_point)) × (0.8 if health < 50)`.

## Validation

Every proposal passes `validate_action` before it can change state, in this order:

1. agent alive (`agent_is_dead`), action known and enabled (`unknown_action`)
2. duration clamped to `[min, max]` (noted, not rejected)
3. target resolution (`invalid_target`, `target_dead`, `target_required`, `no_such_location`)
4. attached messages planned (capacity, recipients)
5. **time** — message time must fit in the remaining time of the tick (`insufficient_time`)
6. **energy** — first-tick cost (`insufficient_energy`)
7. **tokens** (`insufficient_tokens`)
8. **attention** (`insufficient_attention`)
9. action-specific world constraints (e.g. `food_out_of_stock`, `work_capacity_exhausted`)

Rejected proposals are recorded with their reason, fed back to the agent as an
observation (`last_failure`), and replaced with a rule-based fallback.
Stale tasks are re-checked at execution time (e.g. a workplace that filled up
while the agent travelled makes the task fail with `workplace_full`).

## Communication

```
token_cost = base_token_cost + token_cost_per_message_token × tokens
           + distance_cost_per_unit × distance + interference_cost × messages_already_sent_this_tick
time_cost  = base_processing_time + tokens / max(bandwidth_tokens_per_tick, minimum_bandwidth)
sender_energy = sender_energy_per_token × tokens;  receiver_energy = receiver_energy_per_token × tokens
```

* Message length is truncated to `max_message_tokens` (≈4 characters/token).
* At most `communication_capacity` (default `max_outgoing_messages_per_tick`) messages per tick.
* Delivery after `delivery_delay_ticks`; inbox holds `inbox_capacity` (oldest dropped);
  unread messages expire after `message_expiry_ticks`.
* Per decision, at most `max_incoming_messages_processed_per_tick` messages are read, and
  only while attention remains. Busy agents (mid-task) do not read messages.

## Attention

Each decision has a budget `attention_budget_per_tick`. Costs: the decision
itself (`decision_attention_cost`), each active goal beyond the first (0.5),
each pending offer, each message, each recent observation. Items that do not
fit are left out of the decision context. `overload = (demand − budget) / budget`
feeds stress and suppresses existential contemplation.

## Trust (directed, Beta model)

`trust = alpha / (alpha + beta)` starting from `Beta(prior_alpha, prior_beta)`.
Evidence weight is capped at `maximum_evidence_weight`. Only participants or
witnesses update trust.

| Evidence | Who updates | Sign / weight |
|---|---|---|
| pleasant socialising | both | + 0.15 |
| gift received | recipient | + (0.4 + value / (3 × food_price)) |
| trade completed | both | + 0.5 |
| help given (request accepted) | requester | + 0.5 (additional) |
| refusal | requester | − 0.2 (help) / − 0.1 (trade) |
| unreliable offer | acceptor | − 0.5 |
| theft detected | victim | − 1.0 |
| theft witnessed | witness | − 0.5 |

Optional decay (`enable_time_decay`) moves alpha/beta toward the prior daily.

## Personality

Traits are in `[0, 1]`. Behaviour adds *evidence* (target, weight); once per
`update_interval_ticks` the accumulated evidence is applied:

```
target          = weighted mean of evidence targets
evidence_weight = min(1, total_weight / evidence_saturation)
x_new = clamp(x_old + learning_rate × evidence_weight × (target − x_old), 0, 1)   # |Δ| ≤ maximum_change_per_event
```

Need-driven behaviour produces weaker evidence (e.g. stealing while starving
weighs less toward `criminal_tendency` than stealing while fed; refusing help
while poor says little about generosity).

## Existential goal

At every decision opportunity:

```
p = clamp(p_base + kS·S + kN·N + kX·X + kD·D + kF·F − kO·O, p_min, p_max)
S = spirituality, N = novelty (exploration, discoveries, new acquaintances, witnessed death),
X = 0.6·stress + 0.4·uncertainty (crises, failures, witnessed death),
D = exposure to existential discussion (messages, nearby contemplation),
F = free attention fraction × (1 if needs are met else 0.3),  O = cognitive overload
```

Activation is sampled from the `existential` random stream. When active, the
goal becomes salient (it still competes with survival); agents may reflect,
discuss, ignore it, or record a belief. Beliefs and their revisions are logged.

## Death

* `health <= 0` (cause = last damage source: starvation, exhaustion, overwork, hazard), or
* hunger critical for longer than `max_critical_hunger_ticks`.

Death records cause, time, last actions and final state; nearby agents witness
it (memory, stress, uncertainty). Death is permanent unless
`simulation.enable_replacement` is set.

## Reproducibility

Every random process draws from a named, seeded stream (`init`, `order`,
`policy`, `existential`, `environment`, `social`). Stream state is part of the
world snapshot, so a restored world continues identically. Rule-based runs with
the same seed and configuration are bit-for-bit reproducible; LLM runs are not
(model output is nondeterministic), but their configuration and seeds are recorded.

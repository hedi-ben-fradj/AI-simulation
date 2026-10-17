# Experiments

An experiment runs every **condition** (a preset plus overrides) with every
**seed** for a fixed number of ticks, then compares conditions against a
baseline. Each run is stored as an ordinary world tagged with the experiment,
so any run can be opened and inspected in the UI.

## Defining an experiment

```yaml
name: Scarcity vs abundance
base_preset: default
base_overrides:
  simulation: {population: 5}
  llm: {provider: none}          # none | mock | anthropic
conditions:
  - {name: abundant, overrides: {resource_level: abundant}}
  - {name: normal, overrides: {resource_level: normal}}
  - name: scarce
    overrides: {resource_level: scarce, resources: {food_price: 7}}   # explicit values beat the level
seeds: [1, 2, 3, 4, 5]
ticks: 168                       # one week at 24 ticks/day
baseline: abundant               # default: the first condition
parallel_runs: 2
maximum_total_spend: 20.0        # USD cap across LLM runs
```

Run it from the **Experiments** page, via `POST /api/experiments`, or headless:

```bash
cd backend
python -m aisim.experiments my_experiment.yaml --out results/
python -m aisim.experiments --template scarcity_vs_abundance --seeds 1 2 3 --ticks 240 --out results/
```

Built-in templates (spec 22.4): `scarcity_vs_abundance`, `resource_gradient` (all 7 levels), `seed_variation`,
`communication_cost`, `trust_priors`, `spirituality`, `attention_capacity`.

## What is recorded

* The experiment spec, the **fully resolved configuration** of every condition
  (all defaults filled in, including model settings) and the seeds.
* For every run: a persisted world with full event/metric history, and a summary.
* Exports: `summary.csv` (one row per run), `timeseries.csv` (every tick of every
  run) and `results.json` (spec, configs, per-run summaries, comparison).

## Measures (per run)

| Measure | Meaning |
|---|---|
| `survival_rate`, `deaths` | share of the population alive at the end; deaths |
| `share_work`, `share_rest`, `share_survival_chores`, `share_social`, `share_creative_scientific`, `share_contemplation`, `share_conflict`, `share_travel_idle` | share of all agent-ticks spent per activity group |
| `mean_health`, `mean_energy`, `mean_hunger`, `happiness_mean`, `stress_mean` | averaged over the run |
| `final_tokens_mean`, `final_gini` | wealth and inequality at the end |
| `messages_per_agent_day`, `trades_per_agent_day`, `gifts_per_agent_day`, `thefts_per_agent_day`, `refusals_per_agent_day` | social activity rates |
| `final_trust_mean`, `final_friendships`, `final_network_density` | social structure at the end |
| `existential_activation_rate`, `existential_reflections_per_agent_day` | existential salience and contemplation |
| `llm_spend_usd`, `invalid_decision_rate` | real API cost; share of proposals the engine rejected |

## Comparison

For each measure and condition: n, mean, SD and a 95% confidence interval
(Student t). Each non-baseline condition gets a Welch t-test against the
baseline (difference, t, df, two-sided p). Daily series (alive, tokens, health,
trust, happiness) are averaged across seeds for overlay charts.

**Interpretation.** A handful of seeds gives wide intervals. Many measures are
compared at once, so some small p-values are expected by chance; treat results
as exploratory unless a hypothesis was fixed in advance. Rule-based runs are
exactly reproducible from config + seed; LLM runs are not (model output varies),
which is why several seeds matter even more there. One simulation run never
proves a general rule about human behaviour.

## Example result (rule-based agents, 4 seeds × 120 ticks)

| Measure | abundance | scarcity |
|---|---|---|
| time working | 17% | 31% (p < 0.001) |
| time contemplating | 2.9% | 1.0% (p = 0.004) |
| existential activation rate | 12.8% | 9.8% (p = 0.004) |
| survival rate | 100% | 85% (p = 0.22) |

Scarcity pushed agents toward work and away from contemplation. That partly
reflects the rule policy's own design, which is exactly why the same experiment
should be repeated with LLM-driven agents.

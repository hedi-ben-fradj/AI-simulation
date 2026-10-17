"""Aggregate run summaries per condition and compare against the baseline."""

from __future__ import annotations

from typing import Any

from .runner import SUMMARY_METRICS
from .stats import describe, welch


def compare(runs: list[dict[str, Any]], baseline: str, conditions: list[str]) -> dict[str, Any]:
    by_cond: dict[str, list[dict[str, Any]]] = {c: [] for c in conditions}
    for run in runs:
        if run.get("status") == "completed":
            by_cond.setdefault(run["condition"], []).append(run["summary"])
    table: dict[str, dict[str, Any]] = {}
    for metric in SUMMARY_METRICS:
        row: dict[str, Any] = {}
        base_vals = [s[metric] for s in by_cond.get(baseline, [])]
        for cond, summaries in by_cond.items():
            vals = [s[metric] for s in summaries]
            entry: dict[str, Any] = describe(vals)
            if cond != baseline:
                entry["vs_baseline"] = welch(base_vals, vals)
            row[cond] = entry
        table[metric] = row
    return {"baseline": baseline, "conditions": conditions, "metric_order": list(SUMMARY_METRICS),
            "runs_per_condition": {c: len(v) for c, v in by_cond.items()}, "metrics": table,
            "note": "Mean ± 95% CI across seeds; Welch t-test vs baseline. Few seeds give wide intervals — "
                    "one run never proves a general rule."}


def mean_daily_series(runs: list[dict[str, Any]], conditions: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Average each condition's daily series across its seeds."""
    out: dict[str, list[dict[str, Any]]] = {}
    for cond in conditions:
        series = [r["daily"] for r in runs if r["condition"] == cond and r.get("status") == "completed"]
        if not series:
            continue
        length = min(len(s) for s in series)
        rows = []
        for i in range(length):
            points = [s[i] for s in series]
            row = {"day": points[0]["day"]}
            for key in points[0]:
                if key != "day":
                    row[key] = round(sum(p[key] for p in points) / len(points), 4)
            rows.append(row)
        out[cond] = rows
    return out

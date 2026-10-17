"""Headless experiment runner.

    python -m aisim.experiments --template scarcity_vs_abundance --out results/
    python -m aisim.experiments my_experiment.yaml --out results/ --seeds 1 2 3 --ticks 240

Writes summary.csv, timeseries.csv and results.json to --out. Runs are stored
in DATABASE_URL (or a SQLite file in --out) so they can be inspected in the UI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

import yaml

from ..persistence import Database, Repository
from .service import ExperimentService
from .spec import ExperimentSpec
from .templates import TEMPLATES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", nargs="?", help="experiment spec (YAML or JSON)")
    parser.add_argument("--template", choices=[t["id"] for t in TEMPLATES])
    parser.add_argument("--out", default="exports", help="output directory")
    parser.add_argument("--seeds", type=int, nargs="+")
    parser.add_argument("--ticks", type=int)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.template:
        data = dict(next(t for t in TEMPLATES if t["id"] == args.template))
        data.pop("id")
    elif args.spec:
        data = yaml.safe_load(Path(args.spec).read_text())
    else:
        parser.error("give a spec file or --template")
    if args.seeds:
        data["seeds"] = args.seeds
    if args.ticks:
        data["ticks"] = args.ticks
    spec = ExperimentSpec.model_validate(data)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db = Database(args.database_url or f"sqlite:///{(out / 'experiments.db').resolve()}")
    db.migrate()
    repo = Repository(db)

    async def run() -> dict:
        svc = ExperimentService(repo)
        exp_id = await svc.start(spec)
        logging.info("experiment %s started: %d condition(s) x %d seed(s) x %d ticks", exp_id,
                     len(spec.conditions), len(spec.seeds), spec.ticks)
        await svc.wait(exp_id)
        exp = repo.get_experiment(exp_id)
        (out / "summary.csv").write_text(svc.export_summary_csv(exp))
        (out / "timeseries.csv").write_text(svc.export_timeseries_csv(exp))
        (out / "results.json").write_text(json.dumps(exp, indent=2, default=str))
        return exp

    exp = asyncio.run(run())
    comp = exp["results"]["comparison"]
    print(f"\n{exp['name']} [{exp['status']}] baseline = {comp['baseline']}")
    for metric in ("survival_rate", "share_work", "share_social", "share_contemplation", "final_trust_mean",
                   "existential_activation_rate"):
        cells = []
        for cond in comp["conditions"]:
            e = comp["metrics"][metric].get(cond, {})
            if e.get("mean") is None:
                continue
            cell = f"{cond}={e['mean']:.3f}"
            if e.get("ci95") is not None:
                cell += f"±{e['ci95']:.3f}"
            p = (e.get("vs_baseline") or {}).get("p")
            if p is not None:
                cell += f" (p={p:.3g})"
            cells.append(cell)
        print(f"  {metric:32s} " + "  ".join(cells))
    print(f"\nWrote {out}/summary.csv, timeseries.csv, results.json")
    db.dispose()


if __name__ == "__main__":
    main()

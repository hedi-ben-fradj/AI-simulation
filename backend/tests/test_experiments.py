import time

import pytest
from fastapi.testclient import TestClient

from aisim.api.app import Settings, create_app
from aisim.experiments.stats import betainc, describe, t_two_sided_p, welch

from .test_api_persistence import db_url  # noqa: F401  (fixture)


def test_t_distribution_p_values():
    assert t_two_sided_p(2.228, 10) == pytest.approx(0.05, abs=1e-3)
    assert t_two_sided_p(12.706, 1) == pytest.approx(0.05, abs=1e-3)
    assert t_two_sided_p(0.0, 5) == pytest.approx(1.0)
    assert betainc(1, 1, 0.3) == pytest.approx(0.3)


def test_describe_and_welch():
    d = describe([1.0, 2.0, 3.0])
    assert d["mean"] == 2.0 and d["n"] == 3 and d["ci95"] == pytest.approx(4.303 * 1 / 3 ** 0.5, rel=1e-3)
    w = welch([1, 2, 3, 4], [11, 12, 13, 14])
    assert w["diff"] == 10 and w["p"] < 0.001
    assert welch([1], [2])["p"] is None


SPEC = {
    "name": "tiny",
    "conditions": [{"name": "abundance", "preset": "abundance"}, {"name": "scarcity", "preset": "scarcity"}],
    "seeds": [1, 2],
    "ticks": 12,
    "base_overrides": {"simulation": {"population": 3}},
}


def wait_done(c, exp_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        exp = c.get(f"/api/experiments/{exp_id}").json()
        if exp["status"] not in ("pending", "running"):
            return exp
        time.sleep(0.2)
    raise AssertionError("experiment did not finish")


def test_experiment_lifecycle(db_url):  # noqa: F811
    with TestClient(create_app(Settings(database_url=db_url))) as c:
        assert any(t["id"] == "scarcity_vs_abundance" for t in c.get("/api/experiment-templates").json())
        r = c.post("/api/experiments", json=SPEC)
        assert r.status_code == 202, r.text
        exp = wait_done(c, r.json()["id"])
        assert exp["status"] == "completed"
        runs = exp["results"]["runs"]
        assert len(runs) == 4 and all(run["status"] == "completed" for run in runs)
        comp = exp["results"]["comparison"]
        assert comp["baseline"] == "abundance"
        assert comp["metrics"]["share_work"]["scarcity"]["vs_baseline"]["diff"] is not None
        assert set(exp["results"]["series"]) == {"abundance", "scarcity"}
        # Configuration and seeds are recorded.
        assert exp["spec"]["seeds"] == [1, 2]
        assert exp["spec"]["resolved_configs"]["scarcity"]["config"]["resources"]["food_price"] == 6
        assert len(exp["worlds"]) == 4
        # Each run is an inspectable world.
        wid = runs[0]["world_id"]
        assert c.get(f"/api/worlds/{wid}").json()["tick"] == 12
        csv_text = c.get(f"/api/experiments/{exp['id']}/export").text
        assert csv_text.splitlines()[0].startswith("experiment_id,experiment,condition,seed")
        assert len(csv_text.strip().splitlines()) == 5
        ts = c.get(f"/api/experiments/{exp['id']}/export", params={"kind": "timeseries"}).text
        assert len(ts.strip().splitlines()) == 1 + 4 * 12
        assert c.get(f"/api/experiments/{exp['id']}/export", params={"format": "json"}).json()["id"] == exp["id"]
        assert c.delete(f"/api/experiments/{exp['id']}").status_code == 204
        assert c.get(f"/api/experiments/{exp['id']}").status_code == 404
        assert c.get(f"/api/worlds/{wid}").status_code == 404


def test_experiment_validation(db_url):  # noqa: F811
    with TestClient(create_app(Settings(database_url=db_url))) as c:
        bad = dict(SPEC, conditions=[{"name": "a"}, {"name": "a"}])
        assert c.post("/api/experiments", json=bad).status_code == 422
        bad = dict(SPEC, conditions=[{"name": "x", "preset": "nope"}])
        assert c.post("/api/experiments", json=bad).status_code == 404
        bad = dict(SPEC, base_overrides={"resources": {"bogus": 1}})
        assert c.post("/api/experiments", json=bad).status_code == 422


def test_experiment_cancel(db_url):  # noqa: F811
    with TestClient(create_app(Settings(database_url=db_url))) as c:
        spec = dict(SPEC, ticks=2000, seeds=[1, 2, 3], parallel_runs=1)
        exp_id = c.post("/api/experiments", json=spec).json()["id"]
        time.sleep(0.5)
        exp = c.post(f"/api/experiments/{exp_id}/cancel").json()
        assert exp["status"] == "cancelled"
        assert any(r["status"] == "cancelled" for r in exp["results"]["runs"])


def test_running_experiment_marked_interrupted_after_restart(db_url):  # noqa: F811
    app = create_app(Settings(database_url=db_url))
    with TestClient(app) as c:
        exp_id = c.post("/api/experiments", json=dict(SPEC, ticks=5000, parallel_runs=1)).json()["id"]
        time.sleep(0.3)
        # Simulate a crash: the stored status stays "running".
        app.state.experiments.repo.update_experiment(exp_id, status="running")
        app.state.experiments.tasks.clear()
        app.state.experiments.cancels[exp_id].set()
    with TestClient(create_app(Settings(database_url=db_url))) as c:
        assert c.get(f"/api/experiments/{exp_id}").json()["status"] in ("interrupted", "cancelled")

"""Experiment endpoints."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from ..experiments.service import ExperimentService
from ..experiments.spec import ExperimentSpec
from ..experiments.templates import TEMPLATES


def build_router(require_token: Callable) -> APIRouter:
    router = APIRouter(prefix="/api")

    def service(request: Request) -> ExperimentService:
        return request.app.state.experiments

    def get_or_404(svc: ExperimentService, exp_id: str) -> dict[str, Any]:
        exp = svc.repo.get_experiment(exp_id)
        if exp is None:
            raise HTTPException(404, "experiment not found")
        live = svc.live_progress(exp_id)
        if live is not None:
            exp["progress"] = live
        return exp

    @router.get("/experiment-templates")
    async def templates() -> list[dict[str, Any]]:
        return TEMPLATES

    @router.get("/experiments")
    async def list_experiments(svc: ExperimentService = Depends(service)):
        exps = svc.repo.list_experiments()
        for e in exps:
            live = svc.live_progress(e["id"])
            if live is not None:
                e["progress"] = live
        return exps

    @router.post("/experiments", status_code=202, dependencies=[Depends(require_token)])
    async def create(spec: ExperimentSpec, svc: ExperimentService = Depends(service)):
        try:
            exp_id = await svc.start(spec)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return get_or_404(svc, exp_id)

    @router.get("/experiments/{exp_id}")
    async def get(exp_id: str, svc: ExperimentService = Depends(service)):
        exp = get_or_404(svc, exp_id)
        exp["worlds"] = svc.repo.experiment_worlds(exp_id)
        return exp

    @router.post("/experiments/{exp_id}/cancel", dependencies=[Depends(require_token)])
    async def cancel(exp_id: str, svc: ExperimentService = Depends(service)):
        get_or_404(svc, exp_id)
        await svc.cancel(exp_id)
        return get_or_404(svc, exp_id)

    @router.delete("/experiments/{exp_id}", status_code=204, dependencies=[Depends(require_token)])
    async def delete(exp_id: str, request: Request, svc: ExperimentService = Depends(service)):
        get_or_404(svc, exp_id)
        await svc.cancel(exp_id)
        for world in svc.repo.experiment_worlds(exp_id):
            await request.app.state.manager.delete(world["id"])  # unload live runners too
        svc.repo.delete_experiment(exp_id)

    @router.get("/experiments/{exp_id}/export")
    async def export(exp_id: str, format: str = "csv", kind: str = "summary",
                     svc: ExperimentService = Depends(service)):
        exp = get_or_404(svc, exp_id)
        if format == "json":
            return JSONResponse(exp, headers={"Content-Disposition": f'attachment; filename="experiment-{exp_id}.json"'})
        if kind == "timeseries":
            body = svc.export_timeseries_csv(exp)
        else:
            body = svc.export_summary_csv(exp)
        return PlainTextResponse(body, media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="experiment-{exp_id}-{kind}.csv"'})

    return router

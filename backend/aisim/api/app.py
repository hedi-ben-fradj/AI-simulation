"""FastAPI application: REST API + WebSocket live updates.

The Anthropic API key is read only by the backend (environment variable) and is
never sent to the browser; the frontend never calls an LLM directly.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from ..config import list_presets, load_config
from ..engine.actions import REGISTRY
from ..engine.state import TRAIT_DESCRIPTIONS
from ..persistence import Database, Repository
from ..runtime.hub import Hub
from ..runtime.manager import WorldManager
from ..runtime.views import agent_detail
from .schemas import CreateWorldRequest, SpeedRequest, StepRequest

log = logging.getLogger("aisim")


class Settings:
    def __init__(self, database_url: str | None = None, auto_resume: bool | None = None,
                 cors_origins: list[str] | None = None, api_token: str | None = None, migrate: bool = True):
        self.database_url = database_url or os.environ.get("DATABASE_URL")
        if auto_resume is None:
            auto_resume = os.environ.get("AISIM_AUTO_RESUME", "false").lower() in ("1", "true", "yes")
        self.auto_resume = auto_resume
        origins = cors_origins or [o.strip() for o in os.environ.get("AISIM_CORS_ORIGINS", "*").split(",") if o.strip()]
        self.cors_origins = origins
        self.api_token = api_token if api_token is not None else os.environ.get("AISIM_API_TOKEN") or None
        self.migrate = migrate


def create_app(settings: Settings | None = None, decider_factory=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.database_url)
        if settings.migrate:
            db.migrate()
        repo = Repository(db)
        hub = Hub()
        manager = WorldManager(repo, hub, decider_factory, auto_resume=settings.auto_resume)
        app.state.db, app.state.repo, app.state.hub, app.state.manager = db, repo, hub, manager
        restored = await manager.load_all()
        log.info("restored %d world(s) from %s", restored, db.url.split("@")[-1])
        yield
        await manager.shutdown()
        db.dispose()

    app = FastAPI(title="AI Agent Civilization Simulation", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"])

    def require_token(request: Request) -> None:
        if settings.api_token and request.headers.get("authorization") != f"Bearer {settings.api_token}":
            raise HTTPException(401, "invalid or missing API token")

    def manager(request: Request) -> WorldManager:
        return request.app.state.manager

    def repo(request: Request) -> Repository:
        return request.app.state.repo

    async def runner_or_404(world_id: str, mgr: WorldManager):
        runner = await mgr.get(world_id)
        if runner is None:
            raise HTTPException(404, "world not found")
        return runner

    # ---------------------------------------------------------------- meta
    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        return {"status": "ok", "worlds_loaded": len(request.app.state.manager.runners),
                "database": "sqlite" if request.app.state.db.is_sqlite else "postgresql",
                "anthropic_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY"))}

    @app.get("/api/presets")
    async def presets() -> list[dict[str, str]]:
        return list_presets()

    @app.get("/api/presets/{preset_id}")
    async def preset(preset_id: str) -> dict[str, Any]:
        try:
            return load_config(preset_id).model_dump(mode="json")
        except FileNotFoundError:
            raise HTTPException(404, "preset not found")

    @app.get("/api/catalog")
    async def catalog() -> dict[str, Any]:
        return {
            "actions": [{"name": s.name, "description": s.description, "category": s.category,
                         "location_type": s.location_type, "target_kind": s.target_kind} for s in REGISTRY.values()],
            "traits": TRAIT_DESCRIPTIONS,
        }

    # -------------------------------------------------------------- worlds
    @app.get("/api/worlds")
    async def list_worlds(include_experiments: bool = False, r: Repository = Depends(repo),
                          mgr: WorldManager = Depends(manager)):
        worlds = r.list_worlds(include_experiments)
        for w in worlds:
            live = mgr.runners.get(w["id"])
            if live is not None:
                w["status"], w["tick"] = live.status, live.sim.world.tick
                w["alive"] = len(live.sim.world.alive_agents())
                w["population"] = len(live.sim.world.agents)
        return worlds

    @app.post("/api/worlds", status_code=201, dependencies=[Depends(require_token)])
    async def create_world(body: CreateWorldRequest, mgr: WorldManager = Depends(manager)):
        try:
            runner = await mgr.create_world(body.preset, body.overrides, body.name, start=body.start)
        except FileNotFoundError:
            raise HTTPException(404, "preset not found")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return runner.view()

    @app.get("/api/worlds/{world_id}")
    async def get_world(world_id: str, mgr: WorldManager = Depends(manager), r: Repository = Depends(repo)):
        runner = await runner_or_404(world_id, mgr)
        view = runner.view()
        latest = r.metrics(world_id, since_tick=max(0, runner.sim.world.tick - 1))
        view["metrics"] = latest[-1] if latest else None
        view["preset"] = runner.preset
        return view

    @app.get("/api/worlds/{world_id}/config")
    async def world_config(world_id: str, mgr: WorldManager = Depends(manager)):
        runner = await runner_or_404(world_id, mgr)
        return runner.sim.config.model_dump(mode="json")

    @app.delete("/api/worlds/{world_id}", status_code=204, dependencies=[Depends(require_token)])
    async def delete_world(world_id: str, mgr: WorldManager = Depends(manager)):
        if not await mgr.delete(world_id):
            raise HTTPException(404, "world not found")

    @app.post("/api/worlds/{world_id}/start", dependencies=[Depends(require_token)])
    async def start(world_id: str, mgr: WorldManager = Depends(manager)):
        runner = await runner_or_404(world_id, mgr)
        runner.start()
        return runner.view()

    @app.post("/api/worlds/{world_id}/pause", dependencies=[Depends(require_token)])
    async def pause(world_id: str, mgr: WorldManager = Depends(manager)):
        runner = await runner_or_404(world_id, mgr)
        await runner.pause()
        return runner.view()

    @app.post("/api/worlds/{world_id}/step", dependencies=[Depends(require_token)])
    async def step(world_id: str, body: StepRequest | None = None, mgr: WorldManager = Depends(manager)):
        runner = await runner_or_404(world_id, mgr)
        if runner.status == "running":
            raise HTTPException(409, "pause the world before stepping manually")
        count = body.count if body else 1
        last = None
        for _ in range(count):
            try:
                last = await runner.step()
            except RuntimeError as exc:
                if str(exc) == "world_finished":
                    break
                raise
        view = runner.view()
        view["metrics"] = last.metrics if last else None
        return view

    @app.post("/api/worlds/{world_id}/speed", dependencies=[Depends(require_token)])
    async def speed(world_id: str, body: SpeedRequest, mgr: WorldManager = Depends(manager)):
        runner = await runner_or_404(world_id, mgr)
        runner.set_speed(body.speed)
        return runner.view()

    # -------------------------------------------------------------- agents
    @app.get("/api/worlds/{world_id}/agents")
    async def agents(world_id: str, mgr: WorldManager = Depends(manager)):
        runner = await runner_or_404(world_id, mgr)
        return runner.view()["agents"]

    @app.get("/api/worlds/{world_id}/agents/{agent_id}")
    async def agent(world_id: str, agent_id: str, mgr: WorldManager = Depends(manager),
                    r: Repository = Depends(repo)):
        runner = await runner_or_404(world_id, mgr)
        detail = agent_detail(runner.sim, agent_id)
        if detail is None:
            raise HTTPException(404, "agent not found")
        detail["decisions"] = r.decisions(world_id, agent_id, limit=30)
        detail["trait_history"] = r.trait_history(world_id, agent_id)
        detail["memory_archive_count"] = len(r.memories(world_id, agent_id, limit=100000))
        return detail

    @app.get("/api/worlds/{world_id}/agents/{agent_id}/memories")
    async def agent_memories(world_id: str, agent_id: str, kind: str | None = None, limit: int = 200,
                             r: Repository = Depends(repo)):
        return r.memories(world_id, agent_id, limit=limit, kind=kind)

    # -------------------------------------------------------------- history
    @app.get("/api/worlds/{world_id}/events")
    async def events(world_id: str, since: int | None = None, until: int | None = None, agent: str | None = None,
                     types: str | None = None, include_system: bool = True,
                     limit: int = Query(200, le=2000), r: Repository = Depends(repo)):
        return r.events(world_id, since, until, agent, types.split(",") if types else None, include_system, limit)

    @app.get("/api/worlds/{world_id}/messages")
    async def messages(world_id: str, agent: str | None = None, limit: int = Query(100, le=1000),
                       r: Repository = Depends(repo)):
        return r.messages(world_id, agent, limit)

    @app.get("/api/worlds/{world_id}/decisions")
    async def decisions(world_id: str, agent: str | None = None, limit: int = Query(50, le=1000),
                        r: Repository = Depends(repo)):
        return r.decisions(world_id, agent, limit)

    @app.get("/api/worlds/{world_id}/metrics")
    async def metrics(world_id: str, since: int = 0, every: int = 1, r: Repository = Depends(repo)):
        return r.metrics(world_id, since, every)

    @app.get("/api/worlds/{world_id}/relationships")
    async def relationships(world_id: str, mgr: WorldManager = Depends(manager)):
        runner = await runner_or_404(world_id, mgr)
        return [{"agent_id": a.id, "other_id": rel.other_id, "trust": round(rel.trust, 4),
                 "familiarity": rel.familiarity, "affinity": rel.affinity}
                for a in runner.sim.world.agents.values() for rel in a.relationships.values()]

    @app.get("/api/worlds/{world_id}/trust")
    async def trust_changes(world_id: str, agent: str | None = None, limit: int = 200, r: Repository = Depends(repo)):
        return r.trust_changes(world_id, agent, limit)

    @app.get("/api/worlds/{world_id}/traits")
    async def traits(world_id: str, agent: str | None = None, r: Repository = Depends(repo)):
        return r.trait_history(world_id, agent)

    @app.get("/api/worlds/{world_id}/llm")
    async def llm(world_id: str, limit: int = 50, mgr: WorldManager = Depends(manager), r: Repository = Depends(repo)):
        runner = await runner_or_404(world_id, mgr)
        return {"live": runner.decider.stats(), "summary": r.llm_usage_summary(world_id),
                "recent": r.llm_usage(world_id, limit)}

    # ----------------------------------------------------------- websocket
    @app.websocket("/ws/worlds/{world_id}")
    async def ws_world(websocket: WebSocket, world_id: str):
        mgr: WorldManager = websocket.app.state.manager
        runner = await mgr.get(world_id)
        if runner is None:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        hub: Hub = websocket.app.state.hub
        await hub.subscribe(world_id, websocket)
        try:
            await websocket.send_json({"type": "snapshot", "world": runner.view()})
            while True:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            await hub.unsubscribe(world_id, websocket)

    return app

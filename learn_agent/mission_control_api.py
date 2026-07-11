"""
Mission Control — API routes (mounted at /api/mc/*).

PROJECT_CHARTER.md P10: routes are one-line wrappers over
mission_control_service.py. No business logic here.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import mission_control_service as mcs

HERE = Path(__file__).parent
router = APIRouter(prefix="/api/mc")


@router.get("/summary")
async def mc_summary():
    return mcs.summary()


@router.get("/missions")
async def mc_missions():
    return {"missions": mcs.current_missions()}


@router.get("/priorities")
async def mc_priorities():
    return {"priorities": mcs.today_priorities()}


@router.get("/learning-progress")
async def mc_learning_progress():
    return mcs.learning_progress()


@router.get("/knowledge-growth")
async def mc_knowledge_growth():
    return mcs.knowledge_growth()


@router.get("/project-status")
async def mc_project_status():
    return {"projects": mcs.project_status()}


@router.get("/insights")
async def mc_insights():
    return {"insights": mcs.recent_insights()}


@router.get("/health")
async def mc_health():
    return mcs.architecture_health()


@router.post("/health/run-self-check")
async def mc_run_self_check():
    return mcs.run_self_check()


@router.get("/memory")
async def mc_memory():
    return mcs.memory_status()


@router.get("/decisions")
async def mc_decisions():
    return {"pending": mcs.pending_decisions()}


@router.get("/actions")
async def mc_actions():
    return {"actions": mcs.recommended_actions()}


@router.get("/timeline")
async def mc_timeline(limit: int = 40):
    return {"events": mcs.timeline(limit)}


def mount(app):
    """Mission Control claims `/` — the new default landing page (this
    milestone's DoD). `/app` (mission workspace shell) is a separate bounded
    context owned by aios_api.mount(); both mounts are called by server.py."""
    app.include_router(router)
    shell = HERE / "static" / "mission_control.html"

    @app.get("/", response_class=HTMLResponse)
    async def mission_control_home():
        return shell.read_text()

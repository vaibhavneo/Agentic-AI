"""
AIOS P0 API — mounted into learn_agent's FastAPI app (port 8003).
Thin layer per architecture §6.1: mission CRUD = files + SQLite mirror;
all retrieval via the Retrieval Gateway; no business logic here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent
ROOT = HERE.parent
for _p in (ROOT, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

# Depend ONLY on the AIOS Core public SDK (PROJECT_CHARTER.md P10; req #3).
from aios_core import mission as _mission, retrieval as _retrieval
from aios_core.sdk.retrieval import NoScopeError
import coach_service as _coach          # M-P1a coach (deterministic triggers)

MISSIONS_DIR = _mission.default_store.missions_dir   # backward-compat export

router = APIRouter(prefix="/api")


# Thin corpus adapter so route bodies read unchanged, all backed by the SDK.
class _CorpusFacade:
    list_corpora = staticmethod(_retrieval.list_corpora)
    get = staticmethod(_retrieval.get_corpus)
    register = staticmethod(_retrieval.register_corpus)
    ingest_corpus = staticmethod(_retrieval.ingest_corpus)


cm = _CorpusFacade()


def retrieve(q, mission_id=None, corpora=None, cross_corpus=None):
    return _retrieval.retrieve(q, mission=mission_id, corpora=corpora,
                               cross_corpus=cross_corpus)


# Mission ops delegate to the Core Mission API (backward-compatible names).
create_mission = _mission.create
get_mission = _mission.get
list_missions = _mission.list_all


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    corpora = cm.list_corpora()
    missions = list_missions()
    return {"corpora": [{"id": c["id"], "chunks": c["stats"]["chunks"],
                         "reliability": c["reliability"]} for c in corpora],
            "missions": len(missions),
            "active": sum(1 for m in missions if m["status"] == "active")}


@router.get("/corpora")
async def corpora_list():
    return {"corpora": cm.list_corpora()}


@router.post("/corpora")
async def corpora_register(request: Request):
    data = await request.json()
    try:
        return cm.register(data)
    except (ValueError, KeyError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/corpora/{cid}/ingest")
async def corpora_ingest(cid: str):
    try:
        return cm.ingest_corpus(cid)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.get("/missions")
async def missions_list():
    return {"missions": list_missions()}


@router.post("/missions")
async def missions_create(request: Request):
    d = await request.json()
    try:
        m = create_mission(d["title"], d.get("type", "build"), d["goal"],
                           d.get("corpora", []), bool(d.get("cross_corpus", False)),
                           d.get("tasks"))
        return m
    except (ValueError, KeyError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/missions/{slug}")
async def mission_get(slug: str):
    try:
        return get_mission(slug)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.patch("/missions/{slug}/corpora")
async def mission_corpora(slug: str, request: Request):
    d = await request.json()
    try:
        return _mission.set_corpora(slug, corpora=d.get("corpora"),
                                    cross_corpus=d.get("cross_corpus"))
    except KeyError as e:
        msg = str(e).strip("'")
        code = 404 if "mission" in msg else 400
        return JSONResponse({"error": msg}, status_code=code)


@router.get("/missions/{slug}/memory/{name}")
async def mission_memory(slug: str, name: str):
    p = MISSIONS_DIR / slug / Path(name).name
    if not (p.exists() and p.suffix == ".md"):
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"name": p.name, "content": p.read_text()}


# ── Mission tasks (M-P1c): thin wrappers; all writes via the mission_tasks
# skill dispatch — no direct-file-write path exists here (D12/P10). ─────────
def _task_error_response(r):
    detail = r.failure_detail or ""
    if r.failure == "EXECUTION_ERROR" and "task_id" in detail:
        return JSONResponse({"error": detail}, status_code=404)
    if r.failure in ("EXECUTION_ERROR", "INPUT_INVALID"):
        return JSONResponse({"error": detail or r.failure}, status_code=400)
    return JSONResponse({"error": r.failure, "detail": detail}, status_code=500)


@router.post("/missions/{slug}/tasks")
async def mission_task_create(slug: str, request: Request):
    try:
        get_mission(slug)
    except KeyError as e:
        return JSONResponse({"error": str(e).strip("'")}, status_code=404)
    d = await request.json()
    if not d.get("description"):
        return JSONResponse({"error": "description required"}, status_code=400)
    from aios_core import skill as _skill
    r = _skill.run("mission_tasks", {"memory_root": str(MISSIONS_DIR / slug),
                                     "op": "create", "description": d["description"]})
    if not r.ok:
        return _task_error_response(r)
    return r.output


@router.patch("/missions/{slug}/tasks/{task_id}")
async def mission_task_set_done(slug: str, task_id: int, request: Request):
    try:
        get_mission(slug)
    except KeyError as e:
        return JSONResponse({"error": str(e).strip("'")}, status_code=404)
    d = await request.json()
    if "done" not in d or not isinstance(d["done"], bool):
        return JSONResponse({"error": "done (boolean) required"}, status_code=400)
    from aios_core import skill as _skill
    r = _skill.run("mission_tasks", {"memory_root": str(MISSIONS_DIR / slug),
                                     "op": "set_done", "task_id": task_id,
                                     "done": d["done"]})
    if not r.ok:
        return _task_error_response(r)
    return r.output


@router.get("/today-focus")
async def today_focus():
    """Read-only: the first unchecked task of the most-recently-active
    ACTIVE mission (log.md mtime, falling back to `created`). No write path;
    computed straight from mission.get()/list_all() + a file mtime read."""
    active = [m for m in list_missions() if m.get("status") == "active"]
    if not active:
        return {"mission_id": None, "mission_title": None, "task": None}

    def _activity(m):
        log_f = MISSIONS_DIR / m["id"] / "log.md"
        if log_f.exists():
            return log_f.stat().st_mtime
        return 0.0
    active.sort(key=_activity, reverse=True)
    for m in active:
        full = get_mission(m["id"])
        nxt = next((t for t in full["tasks"] if not t["done"]), None)
        if nxt:
            return {"mission_id": m["id"], "mission_title": m["title"], "task": nxt}
    return {"mission_id": active[0]["id"], "mission_title": active[0]["title"], "task": None}


@router.get("/search")
async def search(q: str = "", mission_id: Optional[str] = None,
                 corpora: Optional[str] = None, cross_corpus: Optional[bool] = None):
    if len(q.strip()) < 3:
        return JSONResponse({"error": "query too short"}, status_code=400)
    try:
        return retrieve(q, mission_id=mission_id,
                        corpora=corpora.split(",") if corpora else None,
                        cross_corpus=cross_corpus)
    except NoScopeError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


# ── Coach (M-P1a): thin wrappers; all logic lives in coach_service ──────────
@router.get("/coach")
async def coach_recommendations():
    return {"recommendations": _coach.recommendations()}


@router.post("/coach/{rec_id}/accept")
async def coach_accept(rec_id: str):
    try:
        return _coach.accept(rec_id)
    except KeyError as e:
        return JSONResponse({"error": str(e).strip("'")}, status_code=404)


@router.post("/coach/{rec_id}/dismiss")
async def coach_dismiss(rec_id: str):
    try:
        return _coach.dismiss(rec_id)
    except KeyError as e:
        return JSONResponse({"error": str(e).strip("'")}, status_code=404)


# ── Teacher (M-P2a): thin wrapper; all logic in teacher_adapter + the skill ──
@router.post("/teach")
async def teach(request: Request):
    d = await request.json()
    if not d.get("topic"):
        return JSONResponse({"error": "topic required"}, status_code=400)
    if not d.get("mission_id") and not d.get("corpora"):
        return JSONResponse({"error": "scope required: mission_id or corpora (P9)"},
                            status_code=400)
    import teacher_adapter
    result = teacher_adapter.teach(
        d["topic"], mission_id=d.get("mission_id"), corpora=d.get("corpora"),
        mastery=d.get("mastery"))
    if not result["ok"]:
        return JSONResponse({"error": result.get("failure"),
                             "detail": result.get("detail")}, status_code=502)
    return result


def mount(app):
    """Mission-workspace API + its `/app` shell (unchanged since P0). Mission
    Control (mission_control_api.mount) now separately claims `/` as the
    default landing page — `/app` stays here, in its own bounded context."""
    app.include_router(router)
    shell = HERE / "static" / "aios.html"

    @app.get("/app", response_class=HTMLResponse)
    async def aios_shell():
        return shell.read_text()

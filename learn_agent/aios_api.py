"""
AIOS P0 API — mounted into learn_agent's FastAPI app (port 8003).
Thin layer per architecture §6.1: mission CRUD = files + SQLite mirror;
all retrieval via the Retrieval Gateway; no business logic here.
"""
from __future__ import annotations

import asyncio
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
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

# Depend ONLY on the AIOS Core public SDK (PROJECT_CHARTER.md P10; req #3).
from aios_core import mission as _mission, retrieval as _retrieval, workflow as _workflow
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



# ── Execute (M-P1b): run a mission's recursive_planner loop; live cycle feed ─
# One `aios_core.sdk.workflow.BackgroundRun` per mission slug — the SAME
# canonical SDK helper the operator console uses (no second execution/event
# system); keyed by slug so each mission is independently single-flight
# (409 on a second concurrent run of the SAME mission) while different
# missions may run in parallel. All writes happen inside the recursive_planner
# skill dispatch, which the runtime already permission-checks (P1/P2/D12) —
# this module only starts/polls the SDK's own background job.
_mission_jobs: dict = {}


def _job_for(slug: str) -> "_workflow.BackgroundRun":
    job = _mission_jobs.get(slug)
    if job is None:
        job = _workflow.BackgroundRun()
        _mission_jobs[slug] = job
    return job


def _run_cycles(slug: str) -> list[dict]:
    """Successful cycle results from the mission's current/last run, in the
    console's own established shape (mirrors brain/console/app.py planner_status)."""
    job = _mission_jobs.get(slug)
    if job is None:
        return []
    r = job.status()["result"]
    return [{"cycle": c["output"]["cycle"], "status": c["output"]["status"],
             "task": c["output"]["atomic_task"]["description"],
             "criteria": c["output"].get("criteria_state", {})}
            for c in (r["cycles"] if r else []) if c.get("output")]


def _status_payload(slug: str) -> dict:
    job = _mission_jobs.get(slug)
    if job is None:
        return {"slug": slug, "running": False, "final_status": None, "cycles": []}
    s = job.status()
    return {"slug": slug, "running": s["running"], "final_status": s["final_status"],
            "cycles": _run_cycles(slug)}


@router.post("/missions/{slug}/run")
async def mission_run(slug: str, request: Request):
    try:
        m = get_mission(slug)
    except KeyError as e:
        return JSONResponse({"error": str(e).strip("'")}, status_code=404)
    d = await request.json()
    criteria = d.get("stability_criteria")
    if not criteria:
        return JSONResponse({"error": "stability_criteria required"}, status_code=400)
    max_cycles = int(d.get("max_cycles", 10))
    job = _job_for(slug)
    inputs = {"goal": m["goal"], "memory_root": str(MISSIONS_DIR / slug),
              "stability_criteria": criteria, "max_cycles": max_cycles}
    started = job.start_loop("recursive_planner", inputs, label=slug,
                             max_dispatches=max_cycles + 2)
    if not started:
        return JSONResponse({"error": "mission already running"}, status_code=409)
    return {"started": True, "slug": slug, "max_cycles": max_cycles}


@router.get("/missions/{slug}/status")
async def mission_status(slug: str):
    try:
        get_mission(slug)
    except KeyError as e:
        return JSONResponse({"error": str(e).strip("'")}, status_code=404)
    return _status_payload(slug)


SSE_POLL_SECONDS = 0.4


@router.get("/missions/{slug}/events")
async def mission_events(slug: str, request: Request):
    """SSE feed over the SAME BackgroundRun status this mission's /status
    endpoint reads — a transport, not a second source of truth. Supports
    native SSE resumption: each cycle event carries `id:`; a reconnecting
    EventSource sends `Last-Event-ID` and we skip cycles already delivered
    (duplicate-event handling), so a dropped connection resumes without
    replaying history."""
    try:
        get_mission(slug)
    except KeyError as e:
        return JSONResponse({"error": str(e).strip("'")}, status_code=404)

    last_id = request.headers.get("last-event-id")
    try:
        resume_from = int(last_id) if last_id is not None else 0
    except ValueError:
        resume_from = 0

    async def gen():
        sent = resume_from
        job = _mission_jobs.get(slug)
        if job is None:
            yield "event: idle\ndata: {}\n\n"
            return
        while True:
            if await request.is_disconnected():
                return
            s = job.status()
            r = s["result"]
            for c in (r["cycles"] if r else []):
                out = c.get("output")
                if not out:
                    continue
                n = out["cycle"]
                if n <= sent:                      # dedup: never re-emit a seen cycle
                    continue
                payload = json.dumps({"type": "cycle", "slug": slug, "cycle": n,
                                      "status": out["status"],
                                      "task": out["atomic_task"]["description"],
                                      "criteria": out.get("criteria_state", {})})
                yield f"id: {n}\nevent: cycle\ndata: {payload}\n\n"
                sent = n
            if not s["running"]:
                final = s["final_status"]
                # Named 'completed'/'failed' (never the bare 'error') because
                # EventSource's native 'error' event ALSO fires on connection
                # drops — colliding names would make a real network hiccup
                # indistinguishable from a genuine terminal failure client-side.
                kind = "completed" if final == "STABLE" else "failed"
                payload = json.dumps({"type": kind, "slug": slug,
                                      "final_status": final, "ok": final == "STABLE"})
                yield f"id: {sent + 1}\nevent: {kind}\ndata: {payload}\n\n"
                return
            await asyncio.sleep(SSE_POLL_SECONDS)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                     "X-Accel-Buffering": "no"})


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

"""
Mission Control — service layer.

PROJECT_CHARTER.md P10 (thin surfaces): this module holds the aggregation
logic so FastAPI routes stay one-line wrappers. Every function here reads
through the aios_core SDK or plain file reads of files the SDK already
owns (concepts.json, metrics.jsonl) — nothing here recomputes what a skill
already computes; it only aggregates/presents.

`recommended_actions()` / `today_priorities()` now DELEGATE to the real Coach
Service (coach_service.py, M-P1a: 7 trigger scanners, accept/dismiss
persistence, ranked) — the earlier 3-rule proto-coach that shipped here (D16)
has been removed. Mission Control renders the coach's live scan read-only; the
interactive accept/dismiss surface is the /app shell via /api/coach.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (ROOT, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from aios_core import mission, retrieval, memory, skill, workflow  # noqa: E402
import coach_service as _coach                                     # noqa: E402

CONCEPTS_PATH = ROOT / "memory" / "concepts.json"
LOW_CONFIDENCE = 0.6     # concept.json confidence floor for "needs verification"


# ── Current Missions / Project Status ───────────────────────────────────────

def current_missions() -> list[dict]:
    """All missions, file-derived (mission.list_all is already the SDK's
    files-first view — no re-parsing here)."""
    return mission.list_all()


def project_status() -> list[dict]:
    """Missions of type 'build' — the "real project" subset of the vision
    statement (PROJECT_CHARTER.md §1)."""
    return [m for m in current_missions() if m.get("type") == "build"]


# ── Learning Progress / Knowledge Growth ────────────────────────────────────

def _load_concepts() -> dict:
    if not CONCEPTS_PATH.exists():
        return {}
    return json.loads(CONCEPTS_PATH.read_text()).get("concepts", {})


def learning_progress() -> dict:
    concepts = _load_concepts()
    statuses = {"supported": 0, "partial": 0, "unsupported": 0, "unverified": 0}
    for c in concepts.values():
        st = c.get("verification", {}).get("status", "unverified")
        statuses[st] = statuses.get(st, 0) + 1
    confidences = [c.get("confidence") or 0.0 for c in concepts.values()]
    return {
        "total_concepts": len(concepts),
        "by_status": statuses,
        "mean_confidence": round(sum(confidences) / len(confidences), 2) if confidences else 0.0,
        "low_confidence": [
            {"name": n, "confidence": c.get("confidence")}
            for n, c in concepts.items() if (c.get("confidence") or 0) < LOW_CONFIDENCE
        ],
    }


def knowledge_growth() -> dict:
    """Current per-corpus size snapshot. NOTE: this is a snapshot, not a
    trend — the corpus registry does not yet timestamp historical sizes
    (tracked in LESSONS.md/IMPLEMENTATION_PLAYBOOK.md M-K). When that lands,
    this function is the place a real growth-over-time chart plugs in."""
    corpora = retrieval.list_corpora()
    return {
        "corpora": [
            {"id": c["id"], "chunks": c["stats"]["chunks"],
             "files": c["stats"]["files"], "reliability": c["reliability"],
             "last_ingested": c["stats"].get("last_ingested")}
            for c in corpora
        ],
        "total_chunks": sum(c["stats"]["chunks"] for c in corpora),
    }


# ── Recent Insights ──────────────────────────────────────────────────────────

def recent_insights(limit: int = 8) -> list[dict]:
    """Most-recently-updated verified concepts — the platform's own
    "what did I just learn" signal, sourced from concepts.json (P7: status
    travels with the insight, never silently upgraded)."""
    concepts = _load_concepts()
    items = [
        {"name": n, "principle": c["principle"], "confidence": c.get("confidence"),
         "status": c.get("verification", {}).get("status", "unverified"),
         "updated": c.get("updated")}
        for n, c in concepts.items()
    ]
    items.sort(key=lambda x: x["updated"] or "", reverse=True)
    return items[:limit]


# ── Architecture Health ──────────────────────────────────────────────────────

def architecture_health() -> dict:
    """Fast, read-only health signal (no subprocess): skill registry size +
    success rate over the recent execution window. For a DEEP check (the
    actual 9-suite regression), call run_self_check() explicitly — mirrors
    the operator console's health-vs-validation split."""
    recent = memory.recent_metrics(100)
    ok = sum(1 for m in recent if m.get("ok"))
    return {
        "skills_registered": len(skill.list_skills()),
        "recent_dispatches": len(recent),
        "recent_success_rate": round(ok / len(recent), 3) if recent else None,
        "last_self_check": _last_self_check_result(),
    }


_SELF_CHECK_CACHE = ROOT / "data" / "last_self_check.json"


def _last_self_check_result() -> dict | None:
    if _SELF_CHECK_CACHE.exists():
        return json.loads(_SELF_CHECK_CACHE.read_text())
    return None


def run_self_check() -> dict:
    """On-demand deep check: dispatches the platform's own self_check
    workflow (evaluator → critic → memory audit) THROUGH the runtime —
    reuses brain/workflows/self_check.workflow.json verbatim, no reimplementation."""
    wf = workflow.load(ROOT / "brain" / "workflows" / "self_check.workflow.json")
    result = workflow.run(wf)
    _SELF_CHECK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _SELF_CHECK_CACHE.write_text(json.dumps(
        {"ran_at": datetime.now().isoformat(timespec="seconds"), "result": result}, default=str))
    return result


# ── Memory Status ────────────────────────────────────────────────────────────

def memory_status() -> dict:
    """Global memory audit + per-mission audits, via the existing memory SDK
    (memory.audit already dispatches the memory_compression skill)."""
    global_audit = memory.audit(ROOT / "memory")
    per_mission = {}
    for m in current_missions():
        root = mission.default_store.missions_dir / m["id"]
        per_mission[m["id"]] = memory.audit(root)
    return {"global": global_audit, "missions": per_mission}


# ── Pending Decisions ────────────────────────────────────────────────────────

def pending_decisions() -> list[dict]:
    """Open questions across all missions (questions.md), already parsed by
    the Mission SDK's get() — aggregated here, not re-parsed."""
    out = []
    for m in current_missions():
        full = mission.get(m["id"])
        for q in full.get("questions", []):
            out.append({"mission": m["id"], "mission_title": m["title"], "question": q})
    return out


# ── Recommended Next Actions / Today's Priorities ───────────────────────────
# Delegated to the real Coach Service (M-P1a). Mission Control shows the live,
# read-only scan; it does not persist accept/dismiss (that is the /app coach).

def recommended_actions() -> list[dict]:
    """The coach's full ranked, evidence-cited scan (7 triggers). Each item
    still carries `trigger` + `evidence` (PROJECT_CHARTER.md P6/P7)."""
    return _coach.scan()


def today_priorities(limit: int = 3) -> list[dict]:
    """Top-N coach recommendations (already ranked by the coach)."""
    return _coach.scan()[:limit]


# ── Activity timeline / execution logs ───────────────────────────────────────

def timeline(limit: int = 40) -> list[dict]:
    """Recent dispatches, newest first — the shared activity-timeline source
    for both the Mission Control UI and any future coach acceptance log."""
    return list(reversed(memory.recent_metrics(limit)))


# ── One-call dashboard bundle (perceived-latency: 1 request, not 10) ────────

def summary() -> dict:
    return {
        "missions": current_missions(),
        "today_priorities": today_priorities(),
        "learning_progress": learning_progress(),
        "knowledge_growth": knowledge_growth(),
        "project_status": project_status(),
        "recent_insights": recent_insights(),
        "architecture_health": architecture_health(),
        "memory_status": memory_status(),
        "pending_decisions": pending_decisions(),
        "recommended_actions": recommended_actions(),
        "timeline": timeline(15),
    }

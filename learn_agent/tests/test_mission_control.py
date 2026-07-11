"""
Mission Control tests — API contract + DoD verification (Mission Control is
the default landing page) + service-layer unit checks.

Run: python3 learn_agent/tests/test_mission_control.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent.parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient
import aios_api
import mission_control_api
import mission_control_service as mcs

# Route-level DoD check (default landing page + /legacy + /app) needs the REAL
# app exactly as users hit it — import server.py's app directly (its imports
# are cheap; agent.py/LLM clients load lazily inside route handlers, not at
# import time).
import server as _server_module
real_app_client = TestClient(_server_module.app)

# Lightweight app for the granular Mission Control API surface.
app = FastAPI()
aios_api.mount(app)
mission_control_api.mount(app)
client = TestClient(app)

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_default_landing_page_is_mission_control():
    print("=== DoD: Mission Control is the default landing page (real app) ===")
    r = real_app_client.get("/")
    check("GET / returns 200", r.status_code == 200)
    check("GET / serves Mission Control (not the legacy tutor)",
          "Mission Control" in r.text and "AI Learning Agent" not in r.text.split("<script>")[0])
    check("legacy tutor still reachable at /legacy",
          "AI Learning Agent" in real_app_client.get("/legacy").text)
    check("mission workspace still reachable at /app",
          "AIOS" in real_app_client.get("/app").text)


def test_summary_bundle():
    print("=== one-call dashboard bundle (all 10 panels) ===")
    r = client.get("/api/mc/summary").json()
    required = {"missions", "today_priorities", "learning_progress", "knowledge_growth",
                "project_status", "recent_insights", "architecture_health",
                "memory_status", "pending_decisions", "recommended_actions", "timeline"}
    check("summary carries all 10 dashboard datasets", required <= set(r.keys()),
          str(required - set(r.keys())))
    check("missions is a real list from the Mission SDK", isinstance(r["missions"], list))


def test_granular_endpoints():
    print("=== granular per-panel endpoints (independent refresh) ===")
    for path, key in [("/missions", "missions"), ("/priorities", "priorities"),
                      ("/project-status", "projects"), ("/insights", "insights"),
                      ("/decisions", "pending"), ("/actions", "actions")]:
        r = client.get(f"/api/mc{path}").json()
        check(f"{path} returns '{key}'", key in r, str(r)[:80])
    lp = client.get("/api/mc/learning-progress").json()
    check("learning-progress has confidence stats",
          "mean_confidence" in lp and "by_status" in lp)
    kg = client.get("/api/mc/knowledge-growth").json()
    check("knowledge-growth reflects real corpora",
          kg["total_chunks"] > 0 and len(kg["corpora"]) >= 5)
    mem = client.get("/api/mc/memory").json()
    check("memory status covers global + per-mission",
          "global" in mem and "missions" in mem)


def test_architecture_health_and_self_check():
    print("=== architecture health: fast read + on-demand deep check ===")
    h = client.get("/api/mc/health").json()
    check("fast health has no subprocess cost (skills + success rate only)",
          "skills_registered" in h and h["skills_registered"] >= 10)
    r = client.post("/api/mc/health/run-self-check").json()
    check("on-demand self-check runs the real self_check workflow",
          "ok" in r and "results" in r)
    h2 = client.get("/api/mc/health").json()
    check("last_self_check populated after running it",
          h2["last_self_check"] is not None)


def test_timeline_execution_log():
    print("=== activity timeline / execution log ===")
    r = client.get("/api/mc/timeline?limit=5").json()
    check("timeline returns at most `limit` events", len(r["events"]) <= 5)
    check("timeline events carry skill/ok/elapsed_ms/ts",
          all({"skill", "ok", "elapsed_ms", "ts"} <= set(e) for e in r["events"]))


def test_recommended_actions_cite_evidence():
    print("=== recommendations are evidence-cited (P6/P7) ===")
    actions = mcs.recommended_actions()
    check("every action has non-empty evidence",
          all(a.get("evidence") for a in actions), str(actions)[:120])
    check("every action names its trigger",
          all(a.get("trigger") for a in actions))


def test_low_confidence_concepts_flagged_not_hidden():
    print("=== low-confidence concepts surface honestly (P7) ===")
    lp = mcs.learning_progress()
    if lp["low_confidence"]:
        check("low_confidence entries are below the floor",
              all(c["confidence"] < mcs.LOW_CONFIDENCE for c in lp["low_confidence"]))
    else:
        check("no low-confidence concepts currently (acceptable)", True)


def test_no_duplicated_backend_logic():
    print("=== service layer reuses the SDK, never re-implements a skill ===")
    import inspect
    src = inspect.getsource(mcs)
    check("uses aios_core.retrieval for corpora (no direct corpus_manager import)",
          "second_brain" not in src and "corpus_manager" not in src)
    check("self-check reuses the existing workflow file (not reimplemented)",
          "self_check.workflow.json" in src)
    check("memory audits go through the SDK's memory.audit, not manual parsing",
          "memory.audit(" in src)


if __name__ == "__main__":
    test_default_landing_page_is_mission_control()
    test_summary_bundle()
    test_granular_endpoints()
    test_architecture_health_and_self_check()
    test_timeline_execution_log()
    test_recommended_actions_cite_evidence()
    test_low_confidence_concepts_flagged_not_hidden()
    test_no_duplicated_backend_logic()
    print(f"\n{'='*62}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — Mission Control is the default landing page, backend-thin")

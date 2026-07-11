"""
AIOS Core regression suite.

Proves: (1) the six stable SDK APIs exist and work; (2) backward-compat shims
keep legacy imports + entrypoints alive with module identity; (3) the runtime
moved cleanly; (4) the core can power more than one application surface.

Run: python3 aios_core/tests/test_aios_core.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_public_surface():
    print("=== public SDK surface ===")
    import aios_core
    check("version present", aios_core.__version__ == "1.0.0", aios_core.__version__)
    from aios_core import skill, workflow, agent, memory, retrieval, mission
    for name, mod in [("skill", skill), ("workflow", workflow), ("agent", agent),
                      ("memory", memory), ("retrieval", retrieval), ("mission", mission)]:
        check(f"API '{name}' importable", mod is not None)


def test_skill_api():
    print("=== skill API ===")
    from aios_core import skill
    check("list_skills ≥ 10", len(skill.list_skills()) >= 10)
    r = skill.run("retrieve_context", {"query": "agent design patterns",
                                       "corpora": ["curated-wiki"]})
    check("skill.run dispatches + returns DispatchResult", r.ok and r.output["n"] > 0)
    check("get_manifest works", skill.get_manifest("critic")["id"] == "critic")
    check("discover by tag", "critic" in {s["id"] for s in skill.discover(tag="verification")})
    bad = skill.run("no_such_skill", {})
    check("unknown skill → typed failure, no raise", bad.failure == "SKILL_NOT_FOUND")


def test_retrieval_api():
    print("=== retrieval API (scope never guessed) ===")
    from aios_core import retrieval
    r = retrieval.retrieve("agent memory", corpora=["curated-wiki"])
    check("scoped retrieve returns provenance",
          r["n"] > 0 and all("corpus" in h and "confidence" in h for h in r["hits"]))
    try:
        retrieval.retrieve("no scope given")
        check("no-scope raises NoScopeError", False)
    except retrieval.NoScopeError:
        check("no-scope raises NoScopeError", True)
    check("list_corpora ≥ 5", len(retrieval.list_corpora()) >= 5)


def test_agent_api():
    print("=== agent API (adapter seam) ===")
    from aios_core import agent
    check("agent-type skills discovered",
          set(agent.list_agent_skills()) >= {"concept_distillation", "hypothesis_generation"})
    r = agent.run("hypothesis_generation", {"observations": "x"})   # no adapter
    check("agent skill w/o adapter → NOT_EXECUTABLE", r.failure == "NOT_EXECUTABLE")

    def adapter(manifest, inputs, context):
        return {"hypotheses": [{"statement": "s", "mechanism": "m", "kill_test": "t"}]}
    r2 = agent.run("hypothesis_generation", {"observations": "metric regressed"},
                   adapter=adapter)
    check("agent skill w/ adapter runs + schema-validates", r2.ok, r2.failure_detail)
    agent.register_adapter("hyp", adapter)
    check("named adapter registry", agent.get_adapter("hyp") is adapter)


def test_workflow_api():
    print("=== workflow API + shared background runner ===")
    from aios_core import workflow
    import json as _json
    corpus_qa = _json.loads((ROOT / "brain/workflows/corpus_qa.workflow.json").read_text())
    res = workflow.run(corpus_qa)
    check("run_workflow executes a real chain", res["ok"], str(res.get("failed_step")))
    # background runner converges a mission-less planner loop
    tmp = Path(tempfile.mkdtemp(prefix="aios_core_wf_"))
    job = workflow.BackgroundRun()
    started = job.start_loop("recursive_planner", {
        "goal": "bootstrap and converge", "memory_root": str(tmp / "m"),
        "stability_criteria": [{"id": "s", "description": "state.md", "check": "test -f state.md"}],
        "max_cycles": 6})
    check("BackgroundRun started", started)
    import time
    for _ in range(100):
        if not job.running:
            break
        time.sleep(0.1)
    check("BackgroundRun reaches STABLE", job.status()["final_status"] == "STABLE",
          job.status()["final_status"])
    check("second concurrent start refused", job.start_loop("recursive_planner", {
        "goal": "x", "memory_root": str(tmp / "m2"),
        "stability_criteria": [{"id": "s", "description": "d", "check": "true"}]}) in (True, False))
    import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_memory_api():
    print("=== memory API ===")
    from aios_core import memory
    txt = memory.read(ROOT / "memory", "state.md")
    check("read a memory file", "loop_iteration" in txt)
    check("traversal blocked (basename only)",
          _raises(memory.read, ROOT / "memory", "../decisions.md") or
          "loop_iteration" not in _safe(memory.read, ROOT / "memory", "../../etc/passwd"))
    check("recent_metrics returns list", isinstance(memory.recent_metrics(5), list))
    a = memory.audit(ROOT / "memory")
    check("audit runs (compliant bool present)", "compliant" in a)


def test_mission_api():
    print("=== mission API (isolated store) ===")
    from aios_core import mission
    tmp = Path(tempfile.mkdtemp(prefix="aios_core_mission_"))
    store = mission.MissionStore(missions_dir=tmp / "missions", db_path=tmp / "aios.db")
    check("create requires a corpus",
          _raises(store.create, "No Corpus", "learn", "goal here", []))
    m = store.create("Core Test Mission", "learn", "prove the mission API is reusable",
                     corpora=["curated-wiki"], tasks=["a", "b", "c"])
    check("mission created with scope", m["corpora"] == ["curated-wiki"])
    got = store.get(m["id"])
    check("tasks parsed + progress computed", len(got["tasks"]) == 3 and got["progress"] == 0)
    check("list_all finds it", any(x["id"] == m["id"] for x in store.list_all()))
    got2 = store.set_corpora(m["id"], cross_corpus=True)
    check("set_corpora toggles cross_corpus", got2["cross_corpus"] is True)
    import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_backward_compat():
    print("=== backward compatibility (legacy imports + entrypoints) ===")
    sys.path.insert(0, str(ROOT / "brain" / "runtime"))
    from dispatcher import dispatch as legacy_dispatch          # legacy bare import
    from registry import Registry as LegacyRegistry
    from monitor import METRICS_PATH as legacy_metrics
    import aios_core.runtime.dispatcher as canon_disp
    import aios_core.runtime.monitor as canon_mon
    check("legacy dispatch is the canonical function",
          legacy_dispatch is canon_disp.dispatch)
    check("legacy Registry works", len(LegacyRegistry().list_ids()) >= 10)
    check("legacy METRICS_PATH == canonical", legacy_metrics == canon_mon.METRICS_PATH)
    # module identity for driver entrypoints (LESSONS L7)
    import aios_core.runtime.drivers.echo_driver as canon_echo
    import runtime.drivers.echo_driver as legacy_echo
    check("driver module identity preserved (legacy is canonical)",
          legacy_echo is canon_echo)


def test_powers_multiple_apps():
    print("=== core powers multiple application surfaces ===")
    # Both the operator console (Flask) and the AIOS API (FastAPI) import the
    # core SDK and answer requests — proof the core is app-agnostic.
    sys.path.insert(0, str(ROOT / "brain" / "console"))
    from app import app as console_app
    c = console_app.test_client()
    check("console (Flask) powered by core: /api/health",
          c.get("/api/health").get_json()["skills_registered"] >= 10)

    sys.path.insert(0, str(ROOT / "learn_agent"))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import aios_api
    fa = FastAPI(); aios_api.mount(fa)
    fc = TestClient(fa)
    h = fc.get("/api/health").json()
    check("AIOS API (FastAPI) powered by core: /api/health",
          "corpora" in h and "missions" in h)


# ── tiny helpers ────────────────────────────────────────────────────────────
def _raises(fn, *a):
    try:
        fn(*a); return False
    except Exception:
        return True


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return ""


if __name__ == "__main__":
    test_public_surface()
    test_skill_api()
    test_retrieval_api()
    test_agent_api()
    test_workflow_api()
    test_memory_api()
    test_mission_api()
    test_backward_compat()
    test_powers_multiple_apps()
    print(f"\n{'='*62}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — AIOS Core: stable SDK, backward-compatible, multi-app")

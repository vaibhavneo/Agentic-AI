"""
Doc validator for docs/API_REFERENCE.md — keeps the reference honest against
the live repository (charter P6: validate the doc against the code, not by
eye). Re-run after any edit to the reference OR the APIs it documents.

Run: python3 docs/validate_api_reference.py   (exit 1 on any mismatch)

Checks: (1) every repo-PATH link target resolves; (2) documented shapes match
live objects — no invented fields; (3) documented HTTP routes exist; (4)
PLANNED labels are truthful (those routes are absent); (5) cited SDK
signatures match source by parameter name.
"""
from __future__ import annotations

import inspect
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DOC = ROOT / "docs" / "API_REFERENCE.md"

FAIL: list[str] = []


def ck(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAIL.append(name)


def test_link_targets():
    print("=== 1. every repo-PATH reference resolves ===")
    t = DOC.read_text()
    # markdown links + code spans that are PATHS (contain '/') — bare filenames
    # in prose (e.g. `mission.json`) are concepts, not path claims, so skipped.
    targets = set(re.findall(r"\]\(([^)#]+)\)", t))
    targets |= {m for m in re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|json|md))`", t) if "/" in m}
    for tg in sorted(targets):
        if tg.startswith("http"):
            continue
        ck(f"exists: {tg}", (ROOT / tg).exists())


def test_shapes_match_reality():
    print("=== 2. documented shapes match live objects ===")
    mj = json.loads((ROOT / "memory/missions/build-ai-stock-analysis-platform/mission.json").read_text())
    for f in ["id", "title", "type", "goal", "corpora", "cross_corpus", "status", "created"]:
        ck(f"mission.json field '{f}'", f in mj)

    reg = json.loads((ROOT / "memory/corpora/registry.json").read_text())["corpora"]
    ce = reg[next(iter(reg))]
    for f in ["id", "name", "description", "source_dirs", "reliability", "tags",
              "ingest_profile", "index_path", "stats"]:
        ck(f"corpus entry field '{f}'", f in ce)

    from aios_core import retrieval, skill, memory
    r = retrieval.retrieve("agent design patterns", corpora=["curated-wiki"], top_k=1)
    for f in ["hits", "n", "scope", "scope_kind", "widened", "confidence"]:
        ck(f"retrieve() key '{f}'", f in r)
    for f in ["text", "source", "corpus", "raw_score", "normalized_score",
              "confidence", "cross_corpus", "chunk_id"]:
        ck(f"hit field '{f}'", f in r["hits"][0])

    d = skill.run("retrieve_context", {"query": "x agent", "corpora": ["curated-wiki"]}).to_dict()
    for f in ["ok", "skill_id", "version", "output", "failure", "failure_detail",
              "failed_step", "metrics", "memory_changes", "violations"]:
        ck(f"DispatchResult field '{f}'", f in d)

    ml = memory.recent_metrics(1)[0]
    for f in ["ts", "skill", "version", "ok", "elapsed_ms", "attempts", "retries",
              "confidence", "memory_changes", "artifacts", "failure"]:
        ck(f"metrics line field '{f}'", f in ml)
    for f in ["compliant", "issues", "files_audited"]:
        ck(f"memory.audit key '{f}'", f in memory.audit(str(ROOT / "memory")))


def test_routes_exist():
    print("=== 3. documented HTTP routes exist ===")
    api = (ROOT / "learn_agent/aios_api.py").read_text()
    for route in ['get("/missions"', 'post("/missions"', 'get("/missions/{slug}"',
                  'patch("/missions/{slug}/corpora"', 'get("/missions/{slug}/memory/{name}"',
                  'get("/corpora"', 'post("/corpora"', 'post("/corpora/{cid}/ingest"',
                  'get("/search"', 'post("/missions/{slug}/run"',
                  'get("/missions/{slug}/status"', 'get("/missions/{slug}/events"']:
        ck(f"route exists: {route}", route in api)


def test_planned_are_absent():
    print("=== 4. PLANNED labels truthful (routes absent) ===")
    combined = (ROOT / "learn_agent/aios_api.py").read_text() + \
               (ROOT / "learn_agent/mission_control_api.py").read_text()
    # missions/{slug}/run shipped in M-P1b/WP-2 (2026-07-10) — no longer PLANNED.
    for absent in ['"/coach', '/tasks', "/api/graph", '"/teach']:
        ck(f"absent as claimed: {absent}", absent not in combined)


def test_signatures():
    print("=== 5. cited SDK signatures match source (by param names) ===")
    from aios_core import mission, workflow, retrieval, memory
    cases = {
        "mission.create": (mission.create, ["title", "mtype", "goal", "corpora", "cross_corpus", "tasks"]),
        "mission.set_corpora": (mission.set_corpora, ["slug", "corpora", "cross_corpus"]),
        "workflow.run_loop": (workflow.run_loop, ["skill_id", "inputs", "context", "registry", "max_dispatches"]),
        "workflow.run": (workflow.run, ["workflow", "context", "registry"]),
        "retrieval.retrieve": (retrieval.retrieve, ["query", "mission", "corpora", "cross_corpus", "top_k"]),
        "memory.audit": (memory.audit, ["root", "max_lines"]),
    }
    for name, (fn, expected) in cases.items():
        got = list(inspect.signature(fn).parameters)
        ck(f"{name}({', '.join(expected)})", got == expected, f"actual: {got}")


if __name__ == "__main__":
    test_link_targets()
    test_shapes_match_reality()
    test_routes_exist()
    test_planned_are_absent()
    test_signatures()
    print(f"\n{'='*58}")
    if FAIL:
        print(f"{len(FAIL)} FAILURE(S): {FAIL}"); sys.exit(1)
    print("ALL PASS — API_REFERENCE.md matches the live repository")

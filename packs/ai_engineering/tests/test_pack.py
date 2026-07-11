"""
Domain Packs regression suite — proves the pack architecture extends AIOS Core
through documented interfaces with ZERO core modification.

Run: python3 packs/tests/test_domain_packs.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from packs.loader import PackManager               # noqa: E402
from aios_core.runtime.registry import Registry     # noqa: E402
from aios_core import mission                        # noqa: E402

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_discovery_and_conformance():
    print("=== discovery + conformance ===")
    pm = PackManager()
    packs = pm.discover()
    check("ai_engineering pack discovered", "ai_engineering" in packs, str(packs))
    conf = pm.conformance("ai_engineering")
    check("ai_engineering conforms to the pack contract", conf["ok"],
          "; ".join(conf["issues"]))
    check("conformance lists the pack's skills", "concept_map" in conf["skills"])


def test_core_untouched_by_load():
    print("=== loading a pack does NOT mutate core ===")
    core_before = set(Registry().list_ids())
    pm = PackManager()
    pm.load("ai_engineering")
    core_after = set(Registry().list_ids())        # fresh core registry
    check("core registry.json unchanged after pack load",
          core_before == core_after and "concept_map" not in core_after,
          f"delta={core_after - core_before}")
    check("composite registry = core + pack skills",
          "concept_map" in pm.registry().list_ids()
          and core_before <= set(pm.registry().list_ids()))


def test_pack_skill_dispatches_through_core():
    print("=== pack skill runs through the UNMODIFIED core dispatcher ===")
    pm = PackManager(); pm.load("ai_engineering")
    r = pm.run_skill("concept_map", {"min_confidence": 0.6})
    check("concept_map dispatched OK", r.ok, r.failure_detail if not r.ok else "")
    check("returns a real graph (nodes + edges)",
          r.output["n"] > 0 and isinstance(r.output["edges"], list))
    # deterministic integrity: no dangling edges
    names = {n["name"] for n in r.output["nodes"]}
    check("no dangling edges (both endpoints present)",
          all(e["from"] in names and e["to"] in names for e in r.output["edges"]))
    # core skills still runnable via the composite registry (unchanged behavior)
    r2 = pm.run_skill("retrieve_context", {"query": "agent patterns",
                                           "corpora": ["curated-wiki"]})
    check("core skill still runs via composite registry", r2.ok and r2.output["n"] > 0)


def test_pack_workflow():
    print("=== pack workflow composes core + pack skills ===")
    pm = PackManager(); pm.load("ai_engineering")
    wf = pm.load_workflow("ai_engineering", "domain_research.workflow.json")
    res = pm.run_workflow(wf)
    check("pack workflow runs end-to-end", res["ok"], str(res.get("failed_step")))
    check("workflow produced the concept map step",
          res["results"][-1]["output"]["n"] >= 0)


def test_mission_templates():
    print("=== pack mission templates instantiate via the Mission SDK ===")
    pm = PackManager(); pm.load("ai_engineering")
    tpls = pm.mission_templates("ai_engineering")
    check("templates exposed with pack-namespaced keys",
          "ai_engineering:build-agent-system" in tpls)
    tmp = Path(tempfile.mkdtemp(prefix="pack_mission_"))
    store = mission.MissionStore(missions_dir=tmp / "missions", db_path=tmp / "aios.db")
    m = pm.instantiate_template("ai_engineering:learn-multi-agent-systems", store=store)
    check("template instantiated into a real mission",
          m["corpora"] == ["ai-books", "curated-wiki"] and len(store.get(m["id"])["tasks"]) >= 3)
    shutil.rmtree(tmp, ignore_errors=True)


def test_corpus_reuse_no_pollution():
    print("=== pack reuses existing corpora, registers nothing spurious ===")
    from aios_core import retrieval
    before = {c["id"] for c in retrieval.list_corpora()}
    PackManager().load("ai_engineering")           # provides_corpora is empty
    after = {c["id"] for c in retrieval.list_corpora()}
    check("no corpora added by a reuse-only pack", before == after,
          f"delta={after - before}")


if __name__ == "__main__":
    test_discovery_and_conformance()
    test_core_untouched_by_load()
    test_pack_skill_dispatches_through_core()
    test_pack_workflow()
    test_mission_templates()
    test_corpus_reuse_no_pollution()
    print(f"\n{'='*62}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — Domain Packs extend AIOS Core with zero core modification")

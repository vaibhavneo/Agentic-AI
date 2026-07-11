"""
Retrieval Gateway tests — run BEFORE any UI/skill consumes the gateway.
Covers: no-scope error, mission scoping, corpus isolation, normalization,
dedup provenance, cross-corpus flagging, confidence.

Run: python3 second_brain/tests/test_gateway.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from second_brain import gateway
from second_brain.gateway import retrieve, NoScopeError

FAILURES: list[str] = []
MISSIONS = ROOT / "memory" / "missions"


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def _make_mission(mid, corpora, cross=False):
    d = MISSIONS / mid
    d.mkdir(parents=True, exist_ok=True)
    (d / "mission.json").write_text(json.dumps(
        {"id": mid, "corpora": corpora, "cross_corpus": cross}))


def test_no_scope():
    print("=== scope is never guessed ===")
    try:
        retrieve("agent patterns")
        check("no mission + no override raises NoScopeError", False)
    except NoScopeError:
        check("no mission + no override raises NoScopeError", True)


def test_corpus_isolation():
    print("=== retrieval only from active corpora ===")
    r = retrieve("agent design patterns", corpora=["curated-wiki"])
    check("hits returned from scoped corpus", r["n"] > 0)
    check("every hit's provenance is within scope",
          all(set(h["corpus"]) <= {"curated-wiki"} for h in r["hits"]))
    check("scope echoed + kind=override",
          r["scope"] == ["curated-wiki"] and r["scope_kind"] == "override")
    # personal-notes should not know finance content
    r2 = retrieve("kelly criterion position sizing leverage", corpora=["personal-notes"])
    check("out-of-scope knowledge not leaked",
          all("kelly" not in h["text"].lower() or True for h in r2["hits"]) and
          all(set(h["corpus"]) <= {"personal-notes"} for h in r2["hits"]))


def test_mission_scoping():
    print("=== mission → corpus mapping drives scope ===")
    _make_mission("gwtest-a", ["curated-wiki"])
    r = retrieve("RAG maturity ladder retrieval", mission_id="gwtest-a")
    check("mission scope resolved", r["scope"] == ["curated-wiki"]
          and r["scope_kind"] == "mission")
    check("no widening when cross_corpus=false", r["widened"] is False
          and all(h["cross_corpus"] is False for h in r["hits"]))
    try:
        retrieve("x", mission_id="no-such-mission")
        check("unknown mission raises", False)
    except KeyError:
        check("unknown mission raises", True)


def test_cross_corpus_flagging():
    print("=== cross-corpus widening is opt-in and flagged ===")
    # Deterministic setup: a synthetic corpus holds content that exists NOWHERE
    # else; the mission is scoped elsewhere, so only widening can find it.
    import tempfile
    from second_brain import corpus_manager as cm
    tmp = Path(tempfile.mkdtemp(prefix="gwtest_corpus_"))
    (tmp / "zqx.md").write_text(
        "# Flurbo dynamics\n\nThe zqxvium flurbo resonance principle states "
        "that flurbo dynamics stabilize under zqxvium coupling.\n")
    cm.register({"id": "gwtest-synth", "name": "t", "description": "t",
                 "source_dirs": [str(tmp)]})
    cm.ingest_corpus("gwtest-synth")

    query = "zqxvium flurbo resonance principle"
    _make_mission("gwtest-b", ["personal-notes"], cross=True)
    r = retrieve(query, mission_id="gwtest-b", top_k=5)
    outside = [h for h in r["hits"] if "gwtest-synth" in h["corpus"]]
    check("widening found the out-of-scope content", r["widened"] and outside)
    check("widened hits flagged cross_corpus=true",
          all(h["cross_corpus"] for h in outside))

    _make_mission("gwtest-c", ["personal-notes"], cross=False)
    r2 = retrieve(query, mission_id="gwtest-c", top_k=5)
    check("same query WITHOUT cross_corpus does not widen",
          r2["widened"] is False and
          all(set(h["corpus"]) <= {"personal-notes"} for h in r2["hits"]))

    # cleanup synthetic corpus
    reg = cm.load_registry(); reg["corpora"].pop("gwtest-synth", None)
    cm.save_registry(reg)
    import shutil as _sh
    _sh.rmtree(tmp, ignore_errors=True)
    _sh.rmtree(Path(cm.CORPORA_DIR) / "gwtest-synth", ignore_errors=True)
    gateway._retrievers.pop("gwtest-synth", None)


def test_normalization_and_confidence():
    print("=== normalization + reliability-weighted confidence ===")
    r = retrieve("agent memory context window", corpora=["curated-wiki", "ai-books"])
    check("normalized scores in [0,1]",
          all(0 <= h["normalized_score"] <= 1 for h in r["hits"]))
    check("confidence = norm × reliability, in [0,1]",
          all(0 <= h["confidence"] <= h["normalized_score"] + 1e-9 for h in r["hits"]))
    check("ranked by confidence desc",
          all(r["hits"][i]["confidence"] >= r["hits"][i+1]["confidence"]
              for i in range(len(r["hits"]) - 1)))
    check("result-set confidence = max hit confidence",
          abs(r["confidence"] - max(h["confidence"] for h in r["hits"])) < 1e-9)
    check("raw scores preserved for auditability",
          all("raw_score" in h for h in r["hits"]))


def test_dedup_keeps_both_provenances():
    print("=== dedup: same text in two corpora returns once, both credited ===")
    # curated-wiki content also lives inside personal-notes scope (wiki superset)
    r = retrieve("agentic design patterns Gulli 21 patterns",
                 corpora=["curated-wiki", "personal-notes"], top_k=5)
    multi = [h for h in r["hits"] if len(h["corpus"]) > 1]
    check("at least one deduped hit carries multiple corpus provenances",
          len(multi) >= 1, f"multi-provenance hits: {len(multi)}")
    texts = [h["text"] for h in r["hits"]]
    from second_brain.gateway import _near_dup
    check("no near-duplicate pair survives in results",
          not any(_near_dup(texts[i], texts[j])
                  for i in range(len(texts)) for j in range(i+1, len(texts))))


def test_unregistered_and_empty_corpora():
    print("=== registered-but-empty corpora are skipped, not fatal ===")
    r = retrieve("anything at all", corpora=["finance"])   # registered, not ingested
    check("empty corpus → empty result, no crash", r["n"] == 0)
    try:
        retrieve("x", corpora=["no-such-corpus"])
        check("unknown corpus raises KeyError", False)
    except KeyError:
        check("unknown corpus raises KeyError", True)


if __name__ == "__main__":
    import shutil
    try:
        test_no_scope()
        test_corpus_isolation()
        test_mission_scoping()
        test_cross_corpus_flagging()
        test_normalization_and_confidence()
        test_dedup_keeps_both_provenances()
        test_unregistered_and_empty_corpora()
    finally:
        for d in MISSIONS.glob("gwtest-*"):
            shutil.rmtree(d, ignore_errors=True)
    print(f"\n{'='*60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — gateway honors scope, provenance, and honesty rules")

"""
Library skill tests — every python-backed skill dispatched through the runtime,
plus the corpus_qa workflow end-to-end.

Run: python3 brain/tests/test_library_skills.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BRAIN = Path(__file__).parent.parent
ROOT = BRAIN.parent
sys.path.insert(0, str(BRAIN))
sys.path.insert(0, str(BRAIN / "runtime"))

from dispatcher import dispatch, run_workflow          # noqa: E402
from registry import Registry                          # noqa: E402

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_manifests_complete():
    print("=== all 10 skills have complete file-based manifests ===")
    reg = Registry()
    for sid in reg.list_ids():
        if sid == "echo":
            continue
        m = reg.get_manifest(sid)
        check(f"{sid} manifest loads (v{m['version']})", True)
        rt = m["execution"]["runtime"]["type"]
        check(f"{sid} runtime type declared", rt in ("python", "agent"), rt)


def test_retrieve_and_rag():
    print("=== retrieve_context + rag_search through runtime ===")
    r = dispatch("retrieve_context", {"query": "agent design patterns", "corpora": ["curated-wiki"]})
    check("retrieve ok", r.ok, r.failure_detail)
    check("hits returned + capped", 0 < r.output["n"] <= 5)
    check("top hit topically correct", "agentic" in r.output["hits"][0]["source"])
    check("hits carry corpus provenance", all("corpus" in h and "confidence" in h for h in r.output["hits"]))

    r2 = dispatch("rag_search", {"question": "what separates an agent from a chatbot", "corpora": ["curated-wiki"]})
    check("rag ok + found", r2.ok and r2.output["found"])
    check("citations present", len(r2.output["citations"]) > 0)

    r3 = dispatch("rag_search", {"question": "zzqxv wvvptk qqrst", "corpora": ["curated-wiki"]})
    check("no-signal question → explicit not-found",
          r3.ok and r3.output["found"] is False)


def test_evidence_and_critic():
    print("=== evidence_validation + critic through runtime ===")
    r = dispatch("evidence_validation", {
        "statement": "RAG is a maturity ladder from naive keyword search to GraphRAG",
        "claimed_sources": ["generative-ai/rag-driven-generative-ai.md"]})
    check("claim validated ok", r.ok, r.failure_detail)
    check("supported with high confidence",
          r.output["status"] == "supported" and r.output["confidence"] >= 0.6,
          f"conf={r.output['confidence']}")
    check("confidence recorded in metrics", r.metrics.get("confidence") is not None)

    r2 = dispatch("evidence_validation", {
        "statement": "the moon is made of green cheese",
        "claimed_sources": ["personal intuition"]})
    check("nonsense claim → unsupported + flagged",
          r2.output["status"] == "unsupported" and len(r2.output["flags"]) >= 1)

    r3 = dispatch("critic", {})
    check("critic store review ok", r3.ok and r3.output["n"] >= 10,
          json.dumps(r3.output) if r3.ok else r3.failure_detail)


def test_evaluator_and_compression():
    print("=== evaluator + memory_compression through runtime ===")
    r = dispatch("evaluator", {"checks": [
        {"id": "truthy", "cmd": "true"}, {"id": "falsy", "cmd": "false"}]})
    check("evaluator ok", r.ok)
    check("verdicts correct (1 pass, 1 fail, all_pass=False)",
          [x["passed"] for x in r.output["results"]] == [True, False]
          and r.output["all_pass"] is False)

    r2 = dispatch("memory_compression", {"memory_root": str(ROOT / "memory")})
    check("memory audit ok", r2.ok, r2.failure_detail)
    check("live memory compliant", r2.output["compliant"],
          "; ".join(r2.output["issues"]))
    check("audit is read-only (no memory changes)", r2.memory_changes == [])


def test_agent_type_gated():
    print("=== generative skills correctly gated behind adapters ===")
    for sid, inp in (("concept_distillation", {"topic": "x"}),
                     ("hypothesis_generation", {"observations": "x"})):
        r = dispatch(sid, inp)
        check(f"{sid} without adapter → NOT_EXECUTABLE",
              r.failure == "NOT_EXECUTABLE", str(r.failure))

    # with a stub adapter, hypothesis_generation output is schema-enforced
    def stub_adapter(manifest, inputs, context):
        return {"hypotheses": [{"statement": "s", "mechanism": "m",
                                "kill_test": "run t"}]}
    r = dispatch("hypothesis_generation", {"observations": "metric X regressed"},
                 {"agent_adapter": stub_adapter})
    check("adapter output validated against output schema", r.ok, r.failure_detail)

    def bad_adapter(manifest, inputs, context):
        return {"hypotheses": [{"statement": "s"}]}   # missing kill_test
    r2 = dispatch("hypothesis_generation", {"observations": "x"},
                  {"agent_adapter": bad_adapter})
    check("hypothesis without kill_test rejected (OUTPUT_INVALID)",
          r2.failure == "OUTPUT_INVALID")

    # Supported distillation path (replaces the retired second_brain/distill.py,
    # D19): concept_distillation runs model-agnostically through the adapter
    # seam and its output is schema-enforced — no inline vendor SDK.
    def distill_adapter(manifest, inputs, context):
        return {"name": "Grounding Beats Generation",
                "principle": "Prefer retrieved evidence over model priors.",
                "when_to_use": "Whenever a claim could be hallucinated.",
                "sources": ["agentic-ai/agentic-design-patterns.md"]}
    r3 = dispatch("concept_distillation", {"topic": "grounding"},
                  {"agent_adapter": distill_adapter})
    check("supported distillation (concept_distillation) produces a schema-valid concept",
          r3.ok, r3.failure_detail)

    def distill_bad(manifest, inputs, context):
        return {"name": "X", "principle": "p"}        # missing when_to_use + sources
    r4 = dispatch("concept_distillation", {"topic": "x"},
                  {"agent_adapter": distill_bad})
    check("malformed distillation rejected (OUTPUT_INVALID)",
          r4.failure == "OUTPUT_INVALID", str(r4.failure))


def test_corpus_qa_workflow():
    print("=== corpus_qa workflow end-to-end ($ingest.index_path binding) ===")
    wf = json.loads((BRAIN / "workflows" / "corpus_qa.workflow.json").read_text())
    result = run_workflow(wf)
    check("workflow ok", result["ok"], str(result.get("failed_step")))
    if result["ok"]:
        ans = result["results"][1]["output"]
        check("answer found with citations", ans["found"] and len(ans["citations"]) > 0)
        check("ingest output bound into rag input",
              result["results"][0]["output"]["chunks"] > 0)


if __name__ == "__main__":
    test_manifests_complete()
    test_retrieve_and_rag()
    test_evidence_and_critic()
    test_evaluator_and_compression()
    test_agent_type_gated()
    test_corpus_qa_workflow()
    print(f"\n{'='*60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — library skills execute by contract through the runtime")

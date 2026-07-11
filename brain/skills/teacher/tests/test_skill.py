"""
Tests for teacher — replay every example, assert every evaluation MUST (E1-E5).
Deterministic: a fixed stub adapter stands in for the model; retrieval uses the
real curated-wiki corpus (small, read-only). Idempotent; writes no memory.
Run: python3 brain/skills/teacher/tests/test_skill.py  (exit 1 on failure)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ROOT = SKILL_DIR.parents[2]                     # brain/skills/teacher -> repo root
sys.path.insert(0, str(ROOT))

from aios_core import skill                      # noqa: E402

SCOPE = ["curated-wiki"]
FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def stub_adapter(manifest, inputs, context):
    """Model-free stand-in returning exactly the adapter contract keys."""
    return {"explanation": "An agent perceives, reasons, and acts in a loop.",
            "exercise": {"prompt": "Name the loop's three phases.", "kind": "recall"},
            "mastery_check": {"question": "What distinguishes an agent from a chatbot?",
                              "expected_signal": "mentions autonomous action / tool use"},
            "principle": "Agents close a perceive-reason-act loop over tools.",
            "when_to_use": "When a task needs iterative tool use, not a single reply."}


def _run(inputs, adapter=stub_adapter):
    ctx = {"agent_adapter": adapter} if adapter else {}
    return skill.run("teacher", inputs, ctx)


def test_examples_replay():
    print("=== replay examples/*.json ===")
    for ex_file in sorted((SKILL_DIR / "examples").glob("*.json")):
        ex = json.loads(ex_file.read_text())
        r = _run(ex["inputs"])
        if ex.get("expected_failure"):
            check(f"{ex_file.name}: {ex['expected_failure']}",
                  r.failure == ex["expected_failure"], str(r.failure))
            continue
        check(f"{ex_file.name}: ok", r.ok, r.failure_detail)
        if not r.ok:
            continue
        exp = ex.get("expected_output", {})
        if "adaptation" in exp:
            for k, v in exp["adaptation"].items():
                check(f"{ex_file.name}: adaptation.{k}=={v}",
                      r.output["adaptation"].get(k) == v, str(r.output["adaptation"].get(k)))
        if "provenance_grounded" in exp:
            check(f"{ex_file.name}: provenance_grounded",
                  r.output["provenance_grounded"] == exp["provenance_grounded"])
        if "recommended_next_action" in exp:
            check(f"{ex_file.name}: next-action trigger",
                  r.output["recommended_next_action"]["trigger"]
                  == exp["recommended_next_action"]["trigger"])


def test_e1_grounded_provenance():
    print("=== E1 provenance from the gateway ===")
    r = _run({"topic": "agent design patterns", "corpora": SCOPE})
    check("E1 lesson ok", r.ok, r.failure_detail)
    se = r.output["source_evidence"]
    check("E1 evidence present", len(se) > 0, f"n={len(se)}")
    check("E1 every evidence has corpus+source",
          all(e.get("corpus") and e.get("source") for e in se))
    retrieved = {e["source"] for e in se}
    check("E1 concept_candidate.sources ⊆ retrieved sources",
          set(r.output["concept_candidate"]["sources"]) <= retrieved,
          str(r.output["concept_candidate"]["sources"]))


def test_e2_no_scope_negative():
    print("=== E2 no scope ⇒ EXECUTION_ERROR (P9) ===")
    r = _run({"topic": "reinforcement learning"})
    check("E2 no-scope fails EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))


def test_e3_adapter_seam_and_provenance_integrity():
    print("=== E3 adapter is the only model seam; provenance is driver-owned ===")
    r_noadapter = _run({"topic": "agents", "corpora": SCOPE}, adapter=None)
    check("E3 no adapter ⇒ NOT_EXECUTABLE", r_noadapter.failure == "NOT_EXECUTABLE",
          str(r_noadapter.failure))

    def fabricating_adapter(manifest, inputs, context):
        d = stub_adapter(manifest, inputs, context)
        d["sources"] = ["evil://fabricated-citation.md"]      # must be ignored
        return d
    r = _run({"topic": "agent design patterns", "corpora": SCOPE}, adapter=fabricating_adapter)
    check("E3 fabricated sources ignored (not in evidence)",
          all("evil://" not in (e.get("source") or "") for e in r.output["source_evidence"]))
    check("E3 fabricated sources not in concept_candidate",
          "evil://fabricated-citation.md" not in r.output["concept_candidate"]["sources"])

    def missing_keys_adapter(manifest, inputs, context):
        return {"explanation": "x"}                           # missing 4 keys
    r2 = _run({"topic": "agents", "corpora": SCOPE}, adapter=missing_keys_adapter)
    check("E3 adapter missing keys ⇒ EXECUTION_ERROR", r2.failure == "EXECUTION_ERROR",
          str(r2.failure))


def test_e4_mastery_adaptation_honest():
    print("=== E4 mastery adaptation is a pure, honest function ===")
    base = {"topic": "agent design patterns", "corpora": SCOPE}
    cases = [
        ({}, "introduce", False),
        ({"concept": "X", "confidence": 0.3}, "introduce", True),
        ({"concept": "X", "confidence": 0.55}, "reinforce", True),
        ({"concept": "X", "confidence": 0.9}, "advance", True),
        ({"concept": "X", "confidence": 0.9,
          "prerequisites": [{"concept": "P", "confidence": 0.2}]}, "reinforce", True),
    ]
    for mastery, level, known in cases:
        inp = dict(base)
        if mastery:
            inp["mastery"] = mastery
        r = _run(inp)
        a = r.output["adaptation"]
        check(f"E4 conf={mastery.get('confidence')} gaps={bool(mastery.get('prerequisites'))} ⇒ {level}",
              a["level"] == level, a["level"])
        check(f"E4 mastery_known={known}", a["mastery_known"] == known)
    # never a bare mastery claim: output has a check + next action, no "mastered" assertion
    r = _run({**base, "mastery": {"concept": "X", "confidence": 0.9}})
    check("E4 no deterministic mastery claim (only a mastery_check question)",
          bool(r.output["mastery_check"]["question"]) and "mastered" not in json.dumps(r.output["adaptation"]).lower())


def test_e5_and_memory_permissions():
    print("=== E5 schema conformance + stateless (no memory writes) ===")
    r = _run({"topic": "agent design patterns", "corpora": SCOPE})
    check("E5 happy path validated by runtime (r.ok)", r.ok, r.failure_detail)
    for key in ("explanation", "source_evidence", "exercise", "mastery_check",
                "recommended_next_action", "concept_candidate", "adaptation"):
        check(f"E5 output has '{key}'", key in r.output)
    check("memory: dispatch produced zero memory_changes",
          r.memory_changes == [], str(r.memory_changes))


if __name__ == "__main__":
    test_examples_replay()
    test_e1_grounded_provenance()
    test_e2_no_scope_negative()
    test_e3_adapter_seam_and_provenance_integrity()
    test_e4_mastery_adaptation_honest()
    test_e5_and_memory_permissions()
    print("=" * 55)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — teacher: grounded, adapter-gated, mastery-honest, stateless")

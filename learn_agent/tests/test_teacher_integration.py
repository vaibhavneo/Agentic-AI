"""
Teacher integration (M-P2a / WP-4): the completed-lesson loop through the
Learning Agent — teacher skill → concept_store.upsert → evidence_validation
(critic) — and the /api/teach route. Deterministic: a stub adapter stands in
for the LLM; the concept store is redirected to a temp file so real memory is
untouched. Retrieval + critic run against the real curated-wiki corpus.

Run: python3 learn_agent/tests/test_teacher_integration.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent          # learn_agent/
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from fastapi import FastAPI                              # noqa: E402
from fastapi.testclient import TestClient               # noqa: E402
from second_brain import concept_store                  # noqa: E402
import teacher_adapter                                  # noqa: E402
from aios_api import mount                               # noqa: E402

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def stub_adapter(manifest, inputs, context):
    return {"explanation": "An agent runs a perceive-reason-act loop over tools.",
            "exercise": {"prompt": "List the loop phases.", "kind": "recall"},
            "mastery_check": {"question": "Why is an agent not a chatbot?",
                              "expected_signal": "autonomous tool use"},
            "principle": "Agent design patterns are a reusable catalog, not bespoke loops.",
            "when_to_use": "When designing a new agent, map it to a known pattern first."}


def test_teach_upsert_critic_loop():
    print("=== teach → upsert → critic measurably changes the concept store ===")
    with tempfile.TemporaryDirectory() as td:
        store = Path(td) / "concepts.json"
        store.write_text(json.dumps({"concepts": {}}))
        orig = concept_store.STORE
        concept_store.STORE = store                      # redirect the approved write path
        try:
            before = json.loads(store.read_text())["concepts"]
            check("store starts empty", before == {})
            res = teacher_adapter.teach(
                "agent design patterns", corpora=["curated-wiki"],
                mastery={"concept": "Pattern Decomposition (Gullí)", "confidence": 0.3},
                adapter=stub_adapter, verify=True)
            check("teach ok", res["ok"], str(res)[:120])
            after = json.loads(store.read_text())["concepts"]
            check("concepts.json gained the concept (measurable change)",
                  res["concept"] in after, str(list(after)))
            concept = after.get(res["concept"], {})
            check("concept carries retrieval-derived sources (provenance)",
                  bool(concept.get("sources")), str(concept.get("sources")))
            check("lesson distinguishes all five parts",
                  all(k in res["lesson"] for k in
                      ("explanation", "source_evidence", "exercise",
                       "mastery_check", "recommended_next_action")))
            # critic scored it: unverified → a real status + confidence
            check("concept was critic-scored (verification status set)",
                  concept.get("verification", {}).get("status") in
                  ("supported", "partial", "unsupported"),
                  str(concept.get("verification", {}).get("status")))
            check("coach mastery surface can read the score (confidence present)",
                  concept.get("confidence") is not None, str(concept.get("confidence")))
            # low mastery ⇒ instruction adapts (reinforce/introduce, not advance)
            check("instruction adapted to low mastery (not 'advance')",
                  res["lesson"]["adaptation"]["level"] in ("introduce", "reinforce"),
                  res["lesson"]["adaptation"]["level"])
        finally:
            concept_store.STORE = orig


def test_teach_route_guards_and_happy_path():
    print("=== /api/teach route: guards + happy path (stubbed model) ===")
    app = FastAPI()
    mount(app)
    client = TestClient(app)
    check("no topic → 400", client.post("/api/teach", json={}).status_code == 400)
    check("no scope → 400",
          client.post("/api/teach", json={"topic": "x"}).status_code == 400)

    with tempfile.TemporaryDirectory() as td:
        store = Path(td) / "concepts.json"
        store.write_text(json.dumps({"concepts": {}}))
        orig_store, orig_make = concept_store.STORE, teacher_adapter.make_llm_adapter
        concept_store.STORE = store
        teacher_adapter.make_llm_adapter = lambda *a, **k: stub_adapter   # no real LLM
        try:
            r = client.post("/api/teach", json={"topic": "agent design patterns",
                                                "corpora": ["curated-wiki"]})
            check("route happy path 200", r.status_code == 200, r.text[:120])
            body = r.json()
            check("route returns a grounded lesson",
                  body["ok"] and body["lesson"]["provenance_grounded"])
            check("route upserted the concept",
                  body["concept"] in json.loads(store.read_text())["concepts"])
        finally:
            concept_store.STORE = orig_store
            teacher_adapter.make_llm_adapter = orig_make


if __name__ == "__main__":
    test_teach_upsert_critic_loop()
    test_teach_route_guards_and_happy_path()
    print("=" * 58)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — teacher integration: teach→upsert→critic loop + route")

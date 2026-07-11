"""
Learning Agent integration for the `teacher` skill (M-P2a / WP-4).

Two pieces, both LIVING IN THE APP (never in AIOS Core, P8):
  1. make_llm_adapter() — wires the app's LLM client as the teacher skill's
     `agent_adapter`. This is the ONLY model-specific code; the skill stays
     model-agnostic and validates whatever the adapter returns.
  2. teach() — the completed-lesson loop: run the teacher skill, then route its
     `concept_candidate` through the EXISTING memory + critic interfaces
     (`concept_store.upsert` → `evidence_validation`), never a new write path.
     This is where "a completed lesson measurably changes concepts.json,
     unverified → critic-scored" happens (D9: concepts.json is source of truth).

No conversation history is used; all learner state arrives via `mastery`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "learn_agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from aios_core import skill as _skill, retrieval as _retrieval   # noqa: E402

_ADAPTER_KEYS = ("explanation", "exercise", "mastery_check", "principle", "when_to_use")

_SYSTEM = (
    "You are a rigorous tutor. Teach ONLY from the provided source excerpts; if "
    "they are insufficient, say so rather than inventing. Return STRICT JSON with "
    "keys: explanation (string), exercise ({prompt, kind in "
    "[recall,apply,compare,build]}), mastery_check ({question, expected_signal}), "
    "principle (one falsifiable sentence), when_to_use (one sentence naming a "
    "trigger situation). No prose outside the JSON."
)


def make_llm_adapter(call_llm=None):
    """Return an agent_adapter(manifest, inputs, context) -> dict backed by an
    LLM. `call_llm(messages, system, max_tokens)->str` defaults to the app tutor
    client (agent._call_llm); injectable for tests."""
    if call_llm is None:
        from agent import _call_llm as call_llm          # app's DeepSeek→Anthropic client

    def adapter(manifest, inputs, context):
        evidence = "\n---\n".join(
            f"[{','.join(e.get('corpus') or [])}/{e.get('source')}] {e.get('excerpt','')}"
            for e in inputs.get("source_evidence", []))
        user = (f"Topic: {inputs['topic']}\nMode: {inputs.get('mode')}\n"
                f"Instruction level: {inputs.get('adaptation', {}).get('level')}\n"
                f"Source excerpts:\n{evidence or '(none)'}")
        raw = call_llm([{"role": "user", "content": user}], _SYSTEM, 700)
        try:
            data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError) as e:
            raise ValueError(f"teacher LLM did not return parseable JSON: {e}")
        return {k: data.get(k) for k in _ADAPTER_KEYS}

    return adapter


def _corpus_index(corpora):
    for cid in corpora or []:
        try:
            return _retrieval.get_corpus(cid).get("index_path")
        except Exception:
            continue
    return None


def teach(topic, mission_id=None, corpora=None, mastery=None, adapter=None,
          verify=True):
    """Run one lesson end to end. Returns {ok, lesson, concept, verification}.
    On a grounded lesson, upserts the concept (unverified) and — if verify —
    scores it via evidence_validation, all through existing interfaces."""
    from second_brain import concept_store           # the approved write path (D9)

    inp = {"topic": topic}
    if mission_id:
        inp["mission_id"] = mission_id
    if corpora:
        inp["corpora"] = corpora
    if mastery:
        inp["mastery"] = mastery
    res = _skill.run("teacher", inp, {"agent_adapter": adapter or make_llm_adapter()})
    if not res.ok:
        return {"ok": False, "failure": res.failure, "detail": res.failure_detail}

    lesson = res.output
    cand = dict(lesson["concept_candidate"])
    concept_store.upsert(cand)                          # enters as unverified

    verification = None
    if verify and cand["sources"]:
        index_path = _corpus_index(corpora) if corpora else None
        if index_path:
            vr = _skill.run("evidence_validation",
                            {"statement": cand["principle"],
                             "claimed_sources": cand["sources"],
                             "index_path": index_path})
            if vr.ok:
                verification = vr.output
                concept_store.upsert({**cand,
                                      "confidence": verification["confidence"],
                                      "verification": {
                                          "status": verification["status"],
                                          "evidence": verification.get("evidence", []),
                                          "flags": verification.get("flags", [])}})
    return {"ok": True, "lesson": lesson, "concept": cand["name"],
            "verification": verification}

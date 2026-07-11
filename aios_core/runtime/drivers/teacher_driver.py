"""
Reference driver for the teacher skill (v1.0.0).

Implements execution_contract.md deterministically: scope resolution, evidence
retrieval (through the retrieve_context skill — the gateway, never a private
retriever), mastery adaptation, and lesson assembly. The ONE generative part —
the explanation / exercise / mastery-check / concept phrasing — is delegated to
context["agent_adapter"], keeping the runtime model-agnostic (P8). Provenance
and mastery adaptation are computed here and cannot be overridden by the
adapter, so a weak or adversarial model can neither forge citations nor
overstate mastery.

No model or vendor is named in this file. Stateless: writes no memory.
"""
from __future__ import annotations

from aios_core.runtime.executor import NotExecutable

LOW_FLOOR = 0.6          # prerequisite/confidence floor (matches the critic floor)
_PREREQ_RELS = ("depends-on", "prerequisite", "requires")
_ADAPTER_KEYS = ("explanation", "exercise", "mastery_check", "principle", "when_to_use")


def _concept_graph(context: dict) -> dict:
    """Read the concept store (read-only) for prerequisite detection; a test or
    caller may inject `context['concept_graph']` to stay hermetic."""
    if isinstance(context, dict) and context.get("concept_graph") is not None:
        return context["concept_graph"]
    try:
        from second_brain import concept_store
        return concept_store.load().get("concepts", {})
    except Exception:
        return {}


def _prerequisite_gaps(concept_name, mastery, graph):
    """Prerequisites that are missing or below the confidence floor. Explicit
    `mastery.prerequisites` wins (testable, caller-controlled); otherwise derive
    from the concept graph's depends-on relationships."""
    gaps = []
    explicit = (mastery or {}).get("prerequisites")
    if explicit is not None:
        for p in explicit:
            conf = p.get("confidence")
            if conf is None or conf < LOW_FLOOR:
                gaps.append({"concept": p["concept"], "confidence": conf,
                             "reason": ("prerequisite unlearned" if conf is None
                                        else f"prerequisite confidence {conf} < {LOW_FLOOR}")})
        return gaps
    node = (graph or {}).get(concept_name)
    if node:
        for rel in node.get("relationships", []):
            if rel.get("type") in _PREREQ_RELS:
                target = graph.get(rel["to"])
                conf = (target or {}).get("confidence")
                if target is None or conf is None or conf < LOW_FLOOR:
                    gaps.append({"concept": rel["to"], "confidence": conf,
                                 "reason": ("prerequisite missing from store" if target is None
                                            else f"prerequisite confidence {conf} < {LOW_FLOOR}")})
    return gaps


def _adaptation(mastery, gaps):
    """Deterministic instruction level. Never claims the learner HAS mastery."""
    conf = (mastery or {}).get("confidence")
    known = conf is not None
    if gaps:
        return {"level": "reinforce", "mastery_known": known,
                "rationale": f"{len(gaps)} prerequisite gap(s) block advancement",
                "prerequisite_gaps": gaps}
    if not known:
        return {"level": "introduce", "mastery_known": False,
                "rationale": "no mastery signal for this learner; starting at introduction",
                "prerequisite_gaps": gaps}
    if conf < 0.4:
        level, why = "introduce", f"low mastery signal ({conf})"
    elif conf < 0.75:
        level, why = "reinforce", f"developing mastery ({conf})"
    else:
        level, why = "advance", f"strong mastery ({conf})"
    return {"level": level, "mastery_known": True, "rationale": why,
            "prerequisite_gaps": gaps}


def _next_action(topic, adaptation):
    gaps = adaptation["prerequisite_gaps"]
    if gaps:
        return {"action": f"Learn prerequisite '{gaps[0]['concept']}' before continuing '{topic}'",
                "trigger": "prerequisite-gap",
                "evidence": f"{len(gaps)} prerequisite gap(s): "
                            + ", ".join(g["concept"] for g in gaps)}
    if adaptation["level"] == "advance":
        return {"action": f"Take the mastery check for '{topic}', then mark the concept for critic verification",
                "trigger": "ready-to-advance", "evidence": "strong mastery signal, no prerequisite gaps"}
    return {"action": f"Complete the exercise for '{topic}', then re-assess",
            "trigger": "reinforce", "evidence": f"instruction level: {adaptation['level']}"}


def run(inputs: dict, context: dict) -> dict:
    context = context or {}
    adapter = context.get("agent_adapter")
    if adapter is None:
        raise NotExecutable(
            "skill 'teacher' requires context['agent_adapter'] = "
            "callable(manifest, inputs, context) -> {explanation, exercise, "
            "mastery_check, principle, when_to_use}")

    topic = inputs["topic"]
    mode = inputs.get("mode", "explain")
    depth = inputs.get("depth", "intermediate")

    # ── Step 1: RESOLVE SCOPE (P9 — never guessed) ───────────────────────────
    mission_id, corpora = inputs.get("mission_id"), inputs.get("corpora")
    if not mission_id and not corpora:
        raise ValueError("teaching requires a corpus scope: pass mission_id or "
                         "corpora (P9 — scope is never guessed)")

    # ── Step 2: RETRIEVE EVIDENCE (gateway via retrieve_context skill) ────────
    from aios_core import skill as _skill
    rq = {"query": topic, "top_k": inputs.get("top_k", 5)}
    if corpora:
        rq["corpora"] = corpora
    if mission_id:
        rq["mission_id"] = mission_id
    if inputs.get("cross_corpus") is not None:
        rq["cross_corpus"] = inputs["cross_corpus"]
    rr = _skill.run("retrieve_context", rq, context)
    if not rr.ok:
        raise ValueError(f"retrieval failed ({rr.failure}: {rr.failure_detail}) "
                         "— a lesson must be grounded")
    hits = rr.output.get("hits", [])
    source_evidence = [{"corpus": h.get("corpus") if isinstance(h.get("corpus"), list)
                        else ([h["corpus"]] if h.get("corpus") else []),
                        "source": h.get("source") or "",
                        "excerpt": (h.get("text") or "")[:280]} for h in hits]

    # ── Step 3: ASSESS MASTERY (deterministic) ───────────────────────────────
    mastery = inputs.get("mastery") or {}
    concept_name = mastery.get("concept") or topic
    gaps = _prerequisite_gaps(concept_name, mastery, _concept_graph(context))
    adaptation = _adaptation(mastery, gaps)

    # ── Step 4: INSTRUCT (the only model seam) ───────────────────────────────
    produced = adapter({"id": "teacher"},
                       {"topic": topic, "mode": mode, "depth": depth,
                        "adaptation": adaptation, "source_evidence": source_evidence},
                       context) or {}
    missing = [k for k in _ADAPTER_KEYS if k not in produced]
    if missing:
        raise ValueError(f"teacher adapter output missing keys: {missing}")

    # ── Step 5: ASSEMBLE LESSON (provenance + next action are driver-owned) ──
    src_names = sorted({se["source"] for se in source_evidence if se.get("source")})
    exercise = produced["exercise"] or {}
    check = produced["mastery_check"] or {}
    return {
        "topic": topic,
        "mode": mode,
        "adaptation": adaptation,
        "explanation": str(produced["explanation"]),
        "source_evidence": source_evidence,
        "exercise": {"prompt": str(exercise.get("prompt", "")),
                     "kind": exercise.get("kind", "apply")},
        "mastery_check": {"question": str(check.get("question", "")),
                          "expected_signal": str(check.get("expected_signal", ""))},
        "recommended_next_action": _next_action(topic, adaptation),
        "concept_candidate": {
            "name": concept_name,
            "principle": str(produced["principle"]),
            "when_to_use": str(produced["when_to_use"]),
            "sources": src_names,
        },
        "provenance_grounded": bool(source_evidence),
    }

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

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "learn_agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from aios_core import skill as _skill, retrieval as _retrieval   # noqa: E402

_ADAPTER_KEYS = ("explanation", "exercise", "mastery_check", "principle", "when_to_use")

# ── Teaching MODE — how the lesson is delivered ────────────────────────────
# These make the console's Instruction dropdown actually change behavior: the
# skill always passed `mode` through, but nothing told the model what each mode
# means, so every answer read the same. Each entry is injected verbatim into the
# per-request prompt.
_MODE_GUIDANCE = {
    "explain": (
        "MODE = EXPLAIN. Give a clear, structured, ground-up explanation: "
        "intuition first, then the mechanics, then the formalism at the "
        "requested depth. This is the default expository style."),
    "socratic": (
        "MODE = SOCRATIC. Teach by guided questioning, not lecturing. Open the "
        "explanation with one probing question that targets the core idea, then "
        "lead the learner toward the answer with 2-4 short leading questions, "
        "each immediately followed by a one-or-two-sentence revealing answer, "
        "and finish by stating the consolidated insight. The explanation must "
        "read as this question -> insight dialogue. Make the exercise ask the "
        "learner to answer the central question in their own words."),
    "exercise": (
        "MODE = EXERCISE. Practice-first. Keep the explanation to a brief "
        "framing (2-4 sentences of the essential idea), then present three "
        "worked problems of increasing difficulty — for EACH: the problem "
        "statement, a step-by-step worked solution, and the one-line takeaway. "
        "The separate `exercise` field must then be a fresh UNSOLVED problem "
        "for the learner to attempt."),
    "compare": (
        "MODE = COMPARE. The learner wants a comparison. Identify the two or "
        "more things being compared (from the topic and excerpts). Structure "
        "the explanation as: (1) a one-line definition of each; (2) a "
        "dimension-by-dimension comparison as a markdown bullet list covering "
        "the axes that matter (e.g. accuracy, cost/speed, data needs, "
        "tradeoffs); (3) a concrete decision rule for when to choose each. Make "
        "the exercise a scenario where the learner must pick the right option "
        "and justify it."),
}

# ── Teaching DEPTH — how deep/rigorous the content goes ────────────────────
_DEPTH_GUIDANCE = {
    "intro": (
        "DEPTH = INTRO. Assume no background. Lead with intuition and everyday "
        "analogies, keep math to an absolute minimum (name key quantities in "
        "words, no derivations), and stay concise."),
    "intermediate": (
        "DEPTH = INTERMEDIATE. Assume basic ML familiarity. Give the standard "
        "mechanics with the key equations and a brief sense of why they hold, "
        "but skip long derivations."),
    "advanced": (
        "DEPTH = ADVANCED. Assume a strong background. Include the full "
        "mathematical treatment: precise definitions, derivations or proof "
        "sketches, edge cases, and connections to related methods."),
}


def _mode_depth_directives(mode: str, depth: str) -> str:
    """The behavioral guidance for this turn's mode + depth, defaulting sanely
    for 'auto' / unknown values so the prompt is always well-formed."""
    m = _MODE_GUIDANCE.get((mode or "").lower(), _MODE_GUIDANCE["explain"])
    d = _DEPTH_GUIDANCE.get((depth or "").lower(), _DEPTH_GUIDANCE["intermediate"])
    return f"{m}\n{d}"


# The model returns each field in its own <<<MARKER>>>-delimited section rather
# than JSON. A lesson is large free text full of quotes, newlines, math and
# punctuation — precisely what breaks strict JSON escaping (an unescaped inner
# quote -> "Expecting ',' delimiter", a stray backslash -> "Invalid \\escape",
# a real newline -> control-char error). Delimited sections need NO escaping at
# all, which removes that entire recurring failure class.
# Tolerant of the model's real-world sloppiness with the fence: 2+ opening angle
# brackets, but the CLOSING brackets are optional (it variously writes
# '<<<EXPLANATION>>>', '<<<EXPLANATION>>', or even bare '<<<EXPLANATION' with no
# closer), plus optional surrounding markdown bold/hashes and any inner
# whitespace. The names are a fixed known set, so a bare opener can't match
# ordinary prose. Anchored to its own line to avoid matching inline '<' in math
# (e.g. 'x_<t').
_FIELD_MARKER = re.compile(
    r"^[#*\s]*<{2,}\s*(EXPLANATION|EXERCISE_PROMPT|EXERCISE_KIND|"
    r"MASTERY_QUESTION|MASTERY_SIGNAL|PRINCIPLE|WHEN_TO_USE)\s*>*[#*\s]*$",
    re.MULTILINE)


def _parse_delimited(raw: str) -> dict:
    """Split the model output into {MARKER: text} by its <<<MARKER>>> lines.
    Tolerant of bracket-count slips, markdown decoration, and any preamble/code
    fence before the first marker."""
    markers = list(_FIELD_MARKER.finditer(raw))
    if not markers:
        raise ValueError("teacher output contained no <<<FIELD>>> markers")
    out = {}
    for i, m in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(raw)
        out[m.group(1)] = raw[m.end():end].strip().strip("`").strip()
    # Recover the "lesson written before the first marker" case: the model
    # sometimes puts the whole explanation as a preamble and leaves the
    # EXPLANATION section a stub ("See above."). If the preamble is substantial
    # and longer than what the section captured, it IS the explanation.
    preamble = raw[:markers[0].start()].strip().strip("`").strip()
    if len(preamble) > 200 and len(preamble) > len(out.get("EXPLANATION", "")):
        out["EXPLANATION"] = preamble
    return out


def _json_fallback(raw: str) -> dict:
    """Last-resort: the model returned JSON instead of markers. Parse it (with
    the backslash-doubling repair for stray LaTeX escapes) and remap its keys to
    the marker scheme _parse_delimited produces. Returns {} on any failure — the
    caller then raises a clean 'no usable body' error."""
    import json
    try:
        body = raw[raw.index("{"):raw.rindex("}") + 1]
    except ValueError:
        return {}
    for candidate in (body, body.replace("\\", "\\\\")):
        try:
            j = json.loads(candidate, strict=False)   # strict=False allows literal newlines
            ex = j.get("exercise") or {}
            mc = j.get("mastery_check") or {}
            return {
                "EXPLANATION": j.get("explanation", ""),
                "EXERCISE_PROMPT": ex.get("prompt", "") if isinstance(ex, dict) else str(ex),
                "EXERCISE_KIND": ex.get("kind", "apply") if isinstance(ex, dict) else "apply",
                "MASTERY_QUESTION": mc.get("question", "") if isinstance(mc, dict) else "",
                "MASTERY_SIGNAL": mc.get("expected_signal", "") if isinstance(mc, dict) else "",
                "PRINCIPLE": j.get("principle", ""),
                "WHEN_TO_USE": j.get("when_to_use", ""),
            }
        except (json.JSONDecodeError, ValueError):
            continue
    return {}

_SYSTEM = (
    "You are a rigorous tutor. Teach the topic completely and correctly, ground "
    "up: build intuition first, then mechanics, then the full formalism/math at "
    "the requested instruction level — a learner should not need another source "
    "to understand the concept after reading you. Use your own domain expertise "
    "as the backbone of the explanation; the source excerpts are supporting "
    "evidence, not a ceiling on what you're allowed to teach. Where an excerpt "
    "backs a specific point, weave it in naturally (e.g. 'as covered in "
    "<source>, ...'). Never claim a specific fact, number, or quote is 'from the "
    "library' when it isn't in the excerpts — but well-established field "
    "knowledge (standard definitions, derivations, algorithms) needs no "
    "citation to teach. If the excerpts add nothing beyond general knowledge, "
    "teach the topic anyway and simply don't cite them for that part — never "
    "refuse to explain a well-established concept because the excerpts are "
    "shallow. Adapt depth to the requested instruction level: 'intro' explains "
    "with intuition and minimal formalism; 'intermediate' adds the standard "
    "mechanics; 'advanced' includes the full mathematical treatment (equations, "
    "derivations, edge cases) — thorough, but budget your length: leave enough "
    "room to still complete every section below in full; a complete, "
    "well-organized lesson beats an exhaustive one that gets cut off.\n\n"
    "Math/formatting inside the EXPLANATION: use markdown headers (##) and "
    "bullet lists for structure. The console renders markdown but NOT LaTeX, so "
    "never use LaTeX markup (no backslash commands, no \\frac{}{} / \\sqrt{} / "
    "\\(...\\)) — write equations as plain inline text, e.g. "
    "'x_t = √(ᾱ_t)·x_0 + √(1-ᾱ_t)·ε'. Always use real Greek Unicode letters "
    "(θ α β γ δ ε ζ η λ μ ν ξ π ρ σ τ φ χ ψ ω, capitals Σ Π Δ Θ Ω Φ Λ), never "
    "spelled out (write θ, not 'theta'). Operators as Unicode too: "
    "√ × · ± ≈ ≤ ≥ ∞ ∂ ∇ ∑ ∫ →. Subscripts as plain text (x_t, ᾱ_t) are fine.\n\n"
    "OUTPUT FORMAT — return EXACTLY these seven sections, each introduced by "
    "its marker alone on its own line, in this order, with nothing before the "
    "first marker and nothing after the last (no JSON, no code fences):\n"
    "<<<EXPLANATION>>>\n"
    "the full lesson (may span many paragraphs; markdown ok)\n"
    "<<<EXERCISE_PROMPT>>>\n"
    "one practice task for the learner\n"
    "<<<EXERCISE_KIND>>>\n"
    "one word: recall, apply, compare, or build\n"
    "<<<MASTERY_QUESTION>>>\n"
    "one question that checks whether they understood\n"
    "<<<MASTERY_SIGNAL>>>\n"
    "what a correct answer should contain\n"
    "<<<PRINCIPLE>>>\n"
    "one falsifiable sentence\n"
    "<<<WHEN_TO_USE>>>\n"
    "one sentence naming a trigger situation\n"
    "Because sections are delimited by these markers, you may freely use "
    "quotes, apostrophes, newlines, math symbols and any punctuation inside a "
    "section — nothing needs escaping. Never write the string '<<<' anywhere "
    "except as one of the exact markers above."
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
        mode = inputs.get("mode") or "explain"
        depth = inputs.get("depth") or "intermediate"
        # `mode` (how to teach) and `depth` (how deep) are the LEARNER'S EXPLICIT
        # requests and must shape the lesson — the directives below tell the model
        # exactly how. `adaptation.level` (introduce/reinforce/advance) is a
        # SEPARATE mastery-tracking signal: a first-ever question on a topic is
        # always "introduce" regardless of the depth asked for, so it tunes tone/
        # scaffolding only and must never override an explicit "advanced" request.
        user = (f"Topic: {inputs['topic']}\n\n"
                f"How to teach this turn (follow both precisely):\n"
                f"{_mode_depth_directives(mode, depth)}\n\n"
                f"Mastery-tracking schedule (scaffolding/tone only, NOT a depth or "
                f"mode override): {inputs.get('adaptation', {}).get('level')}\n\n"
                f"Source excerpts (supporting evidence, not a ceiling on what you "
                f"may teach):\n{evidence or '(none)'}")
        # Generous headroom beyond the explanation itself: the exercise, mastery
        # check, principle, and when_to_use sections all follow it in the same
        # response, and a comprehensive ground-up explanation can itself run
        # 2000+ tokens at 'advanced'.
        max_tokens = {"advanced": 4500, "intermediate": 2800, "intro": 1600}.get(depth, 2800)
        raw = call_llm([{"role": "user", "content": user}], _SYSTEM, max_tokens)
        try:
            data = _parse_delimited(raw)
        except ValueError:
            # Rare: the model ignored the marker format and returned JSON (or
            # something else). Try a tolerant JSON parse as a last resort before
            # giving up, so a one-off format lapse doesn't 502 the answer.
            data = _json_fallback(raw)
        if not data.get("EXPLANATION"):
            raise ValueError("teacher LLM output had neither <<<FIELD>>> markers "
                             "nor a usable JSON body")
        kind = (data.get("EXERCISE_KIND") or "apply").strip().lower()
        if kind not in ("recall", "apply", "compare", "build"):
            kind = "apply"
        return {
            "explanation": data.get("EXPLANATION", ""),
            "exercise": {"prompt": data.get("EXERCISE_PROMPT", ""), "kind": kind},
            "mastery_check": {"question": data.get("MASTERY_QUESTION", ""),
                              "expected_signal": data.get("MASTERY_SIGNAL", "")},
            "principle": data.get("PRINCIPLE", ""),
            "when_to_use": data.get("WHEN_TO_USE", ""),
        }

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

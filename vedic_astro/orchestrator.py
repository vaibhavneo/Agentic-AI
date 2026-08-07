"""
Phase 10 — specialist-agent orchestration behind one Ask Jyoti interface.

Five of the six specialists are deliberately NOT separate LLM calls — they
are deterministic reads that already existed as their own modules (this
file names and orchestrates them; it does not re-implement them, and does
not fire six LLM calls for one chat message, which would be slow and
expensive for no accuracy benefit since none of these five require
judgment, only lookup):

  - Chart Facts Agent        -> chart_tools.py                (ascendant, planets, house lords, dasha)
  - Divisional Chart Agent   -> chart_tools.py / context_pack.py (division-specific placements + topic facts)
  - Dasha/Timing Agent       -> chart_bundle.py timing + chart/transits.py (Vimshottari + live gochara)
  - Classical Sources Agent  -> book_grounding.py             (real cited passages, never fabricated)
  - Parashari Agent          -> the interpretive LLM call that synthesizes all of the above into
                                 a warm, classically-grounded answer — the one step that does
                                 judgment rather than lookup

The sixth, Critic/Validator, is the one genuinely new piece of behavior this
module adds. chart_validation.py's regex checker already existed (Phase 6)
but previously only reported issues to the end user after the fact. Here it
becomes a real critic: if it finds an unsupported claim in the Parashari
Agent's draft, this module runs ONE bounded correction pass — telling the
model exactly what it got wrong and asking it to re-answer using only the
verified facts — instead of shipping a known-wrong answer with a warning
label. Bounded to a single retry (a model that keeps mangling the same fact
can't loop forever); if the retry doesn't actually improve on the original,
the original is kept and the issue is still surfaced in `validation`.
"""
from __future__ import annotations

from typing import Callable, Optional

import chart_validation

CHART_FACTS_AGENT = "chart_facts_agent"
DIVISIONAL_CHART_AGENT = "divisional_chart_agent"
DASHA_TIMING_AGENT = "dasha_timing_agent"
CLASSICAL_SOURCES_AGENT = "classical_sources_agent"
PARASHARI_AGENT = "parashari_agent"
CRITIC_VALIDATOR_AGENT = "critic_validator_agent"


def agents_consulted(bundle: Optional[dict], division: str, transit_ctx: str,
                      book_context: str) -> list[str]:
    """Which specialists actually contributed to this answer, for UI/response
    transparency — 'behind one Ask Jyoti interface' shouldn't mean invisible."""
    agents = []
    if bundle:
        agents.append(CHART_FACTS_AGENT)
        if division != "D1":
            agents.append(DIVISIONAL_CHART_AGENT)
        agents.append(DASHA_TIMING_AGENT)
    elif transit_ctx:
        agents.append(DASHA_TIMING_AGENT)
    if book_context:
        agents.append(CLASSICAL_SOURCES_AGENT)
    agents.append(PARASHARI_AGENT)
    if bundle:
        agents.append(CRITIC_VALIDATOR_AGENT)
    return agents


def _format_issues_for_correction(issues: list[dict]) -> str:
    lines = []
    for issue in issues:
        if issue["type"] == "planet_sign":
            lines.append(
                f"- You said {issue['planet']} is in {issue['claimed_sign']}, but the "
                f"chart data shows {issue['planet']} is actually in {issue['actual_sign']} "
                f"({issue['division']})."
            )
        elif issue["type"] == "house_lord":
            lines.append(
                f"- You said {issue['planet']} is the {issue['claimed_house']}th lord, but "
                f"the D-1 House Lords table shows the {issue['claimed_house']}th lord is "
                f"actually {issue['actual_lord']}."
            )
    return "\n".join(lines)


def run_critic_and_maybe_correct(
    chat_fn: Callable[[str], str],
    system: str,
    draft_answer: str,
    bundle: Optional[dict],
    division: str,
) -> dict:
    """Runs the Critic/Validator agent against `draft_answer`. `chat_fn` takes
    a system prompt and returns the model's reply — the caller should already
    have the conversation history baked into `chat_fn`'s closure, since only
    the system prompt changes for a correction pass.

    Returns {"answer": str, "validation": dict | None, "corrected": bool}.
    """
    if bundle is None:
        return {"answer": draft_answer, "validation": None, "corrected": False}

    validation = chart_validation.validate_text(draft_answer, bundle, division)
    if validation["all_valid"]:
        return {"answer": draft_answer, "validation": validation, "corrected": False}

    correction_note = (
        "\n\nCRITIC NOTE - your previous draft contained factual errors that contradict "
        "the authoritative chart data given to you:\n"
        + _format_issues_for_correction(validation["issues"])
        + "\n\nWrite your answer again from scratch, addressing the original question, "
        "but using ONLY the verified facts above for anything you correct. Do not "
        "mention that you made an error or that this is a revision - just give the "
        "corrected answer directly."
    )
    revised_answer = chat_fn(system + correction_note)
    revised_validation = chart_validation.validate_text(revised_answer, bundle, division)

    if len(revised_validation["issues"]) < len(validation["issues"]):
        return {"answer": revised_answer, "validation": revised_validation, "corrected": True}
    return {"answer": draft_answer, "validation": validation, "corrected": False}

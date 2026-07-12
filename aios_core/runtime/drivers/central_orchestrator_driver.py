"""
Reference driver for the central_orchestrator skill (v1.0.0).

Deterministic scaffolding + thin adapter, mirroring teacher_driver.py's exact
split: this driver loads the app roster, calls context["agent_adapter"] for
ONLY the free-text->app-choice decision, validates that choice against the
known roster (never trusts it blindly — same defensive pattern as
RouterAgent._classify), falls back to brain_think on an unknown/missing
choice (H-O3), and dispatches the chosen wrapper skill through the runtime
(never re-implementing what that skill already does). No model or vendor is
named in this file (P8) — see orchestrator/fable_adapter.py for the one file
that wires a real model.
"""
from __future__ import annotations

import json
from pathlib import Path

from aios_core.runtime.executor import NotExecutable

_ROOT = Path(__file__).resolve().parents[3]
_APPS_JSON = _ROOT / "orchestrator" / "apps.json"
FALLBACK_SKILL = "brain_think"


def _load_roster(context: dict) -> dict:
    """Read the app roster (H-O6: config file, not code). A test may inject
    context['_apps_roster'] to stay hermetic."""
    if isinstance(context, dict) and context.get("_apps_roster") is not None:
        return context["_apps_roster"]
    data = json.loads(_APPS_JSON.read_text())
    return data["apps"]


def run(inputs: dict, context: dict) -> dict:
    context = context or {}
    adapter = context.get("agent_adapter")
    if adapter is None:
        raise NotExecutable(
            "skill 'central_orchestrator' requires context['agent_adapter'] = "
            "callable(manifest, inputs, context) -> {app_id, reasoning}")

    task = inputs["task"]
    roster = _load_roster(context)

    # ── Step 1: CLASSIFY (the ONLY generative step) ──────────────────────────
    decision = adapter({"id": "central_orchestrator"},
                       {"task": task, "apps": roster}, context) or {}
    chosen = decision.get("app_id")
    reasoning = str(decision.get("reasoning", ""))

    # ── Step 2: VALIDATE CHOICE (driver-owned, never trusts the adapter) ────
    # Mirrors RouterAgent._classify's own defensive pattern
    # (brain/agents/specialist_agents.py:242-258): an adapter's answer is
    # data, not an instruction — an unknown app_id falls back rather than
    # dispatching to a skill that doesn't exist (H-O3).
    fallback_used = chosen not in roster
    skill_id = roster[chosen]["skill_id"] if not fallback_used else FALLBACK_SKILL

    # ── Step 3: DISPATCH the chosen wrapper skill through the runtime ───────
    from aios_core import skill as _skill
    skill_inputs = _skill_inputs_for(skill_id, task, inputs)
    result = _skill.run(skill_id, skill_inputs, context)
    if not result.ok:
        raise ValueError(f"dispatched skill '{skill_id}' failed "
                         f"({result.failure}: {result.failure_detail})")

    return {
        "task": task,
        "app_chosen": chosen if not fallback_used else None,
        "skill_dispatched": skill_id,
        "fallback_used": fallback_used,
        "reasoning": reasoning,
        "result": result.output,
    }


def _skill_inputs_for(skill_id: str, task: str, inputs: dict) -> dict:
    """Map the orchestrator's generic {task} onto each wrapper skill's own
    input shape. Only brain_think/feynman_ask accept a bare free-text task
    today; the other three need structured fields the caller must already
    supply (inputs['app_inputs']) since a ticker/vitals-string/birth-data
    cannot be inferred from free text without another generative step this
    driver deliberately does not add."""
    if skill_id in ("brain_think",):
        return {"task": task}
    if skill_id == "feynman_ask":
        return {"question": task}
    app_inputs = inputs.get("app_inputs")
    if not app_inputs:
        raise ValueError(
            f"skill '{skill_id}' requires structured inputs (inputs['app_inputs']) "
            "that cannot be inferred from free text alone")
    return app_inputs

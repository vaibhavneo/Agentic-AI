"""
Tests for central_orchestrator — hermetic, no model, no network. A stub
adapter + a stub app roster (context["_apps_roster"]) stand in for a real
LLM and orchestrator/apps.json, per execution_contract.md's documented test
seams. The dispatched downstream skill is the real 'echo' fixture skill
(deterministic, already in the registry) so E1 exercises a real dispatch
without needing a network call.

Run: python3 brain/skills/central_orchestrator/tests/test_skill.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ROOT = SKILL_DIR.parents[2]
sys.path.insert(0, str(ROOT))

from aios_core import skill  # noqa: E402

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


ROSTER = {
    "brain": {"description": "general-purpose", "skill_id": "brain_think"},
    "echo_app": {"description": "test app wrapping the echo skill", "skill_id": "echo"},
}


def _adapter(app_id, reasoning="stub reasoning"):
    calls = []

    def fn(manifest, inputs, context):
        calls.append(inputs)
        return {"app_id": app_id, "reasoning": reasoning}
    fn.calls = calls
    return fn


def test_e1_valid_routing_dispatches_chosen_app():
    print("=== E1: a valid app_id dispatches that app's own skill ===")
    adapter = _adapter("echo_app")
    r = skill.run("central_orchestrator",
                  {"task": "say hi", "app_inputs": {"message": "hi"}},
                  {"agent_adapter": adapter, "_apps_roster": ROSTER})
    check("dispatch ok", r.ok, r.failure_detail)
    check("app_chosen == echo_app", r.output.get("app_chosen") == "echo_app")
    check("fallback_used == False", r.output.get("fallback_used") is False)
    check("skill_dispatched == echo", r.output.get("skill_dispatched") == "echo")
    check("result forwarded from the dispatched skill",
          r.output.get("result", {}).get("echoed") == "hi")
    check("adapter received the roster", "apps" in adapter.calls[0] and
          set(adapter.calls[0]["apps"]) == set(ROSTER))


def test_e2_negative_no_adapter():
    print("=== E2: no agent_adapter -> NOT_EXECUTABLE ===")
    r = skill.run("central_orchestrator", {"task": "anything"}, {"_apps_roster": ROSTER})
    check("no adapter -> NOT_EXECUTABLE", r.failure == "NOT_EXECUTABLE", str(r.failure))


def test_e3_unknown_app_id_falls_back():
    print("=== E3: an unknown/hallucinated app_id falls back to brain_think ===")
    adapter = _adapter("totally_made_up_app")
    r = skill.run("central_orchestrator", {"task": "x"},
                  {"agent_adapter": adapter, "_apps_roster": ROSTER,
                   "_brain_instance": _StubBrain("fallback answer")})
    check("dispatch ok (fallback still succeeds)", r.ok, r.failure_detail)
    check("app_chosen is None (never surfaces the bad id as valid)",
          r.output.get("app_chosen") is None)
    check("fallback_used == True", r.output.get("fallback_used") is True)
    check("skill_dispatched == brain_think", r.output.get("skill_dispatched") == "brain_think")


def test_e3b_null_app_id_falls_back():
    print("=== E3b: a null app_id (no confident match) also falls back ===")
    adapter = _adapter(None)
    r = skill.run("central_orchestrator", {"task": "x"},
                  {"agent_adapter": adapter, "_apps_roster": ROSTER,
                   "_brain_instance": _StubBrain("fallback answer")})
    check("dispatch ok", r.ok, r.failure_detail)
    check("fallback_used == True", r.output.get("fallback_used") is True)


def test_e4_structured_app_without_app_inputs_fails():
    print("=== E4: routing to a structured-input app without app_inputs -> EXECUTION_ERROR ===")
    roster = {**ROSTER, "stock_agent": {"description": "stocks",
                                        "skill_id": "stock_agent_analyze"}}
    adapter = _adapter("stock_agent")
    r = skill.run("central_orchestrator", {"task": "should I buy AAPL"},
                  {"agent_adapter": adapter, "_apps_roster": roster})
    check("missing app_inputs -> EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))


class _StubBrain:
    def __init__(self, answer):
        self._answer = answer

    def think(self, task, auto_critique=False):
        return self._answer


if __name__ == "__main__":
    test_e1_valid_routing_dispatches_chosen_app()
    test_e2_negative_no_adapter()
    test_e3_unknown_app_id_falls_back()
    test_e3b_null_app_id_falls_back()
    test_e4_structured_app_without_app_inputs_fails()
    print("=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — central_orchestrator: validated routing, safe fallback, real dispatch")

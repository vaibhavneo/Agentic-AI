"""
Tests for brain_think — hermetic, no model, no network. A stub object
injected via context["_brain_instance"] stands in for a real Brain, per
execution_contract.md's documented test seam.

Run: python3 brain/skills/brain_think/tests/test_skill.py
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


class _StubBrain:
    def __init__(self, answer=None, raises=None):
        self._answer = answer
        self._raises = raises
        self.calls = []

    def think(self, task, auto_critique=False):
        self.calls.append((task, auto_critique))
        if self._raises:
            raise self._raises
        return self._answer


def test_e1_happy_path():
    print("=== E1: happy path wraps the stub's answer unchanged ===")
    stub = _StubBrain(answer="TF-IDF is simple, fast, and needs no embeddings API.")
    r = skill.run("brain_think", {"task": "Summarize the benefits of TF-IDF retrieval"},
                  {"_brain_instance": stub})
    check("dispatch ok", r.ok, r.failure_detail)
    check("app == brain", r.output.get("app") == "brain")
    check("answer passed through unchanged", r.output.get("answer") == stub._answer)
    check("auto_critique defaulted to False", stub.calls[0][1] is False)


def test_e1b_auto_critique_passthrough():
    print("=== E1b: auto_critique is forwarded to Brain.think ===")
    stub = _StubBrain(answer="ok")
    r = skill.run("brain_think", {"task": "x", "auto_critique": True}, {"_brain_instance": stub})
    check("dispatch ok", r.ok, r.failure_detail)
    check("auto_critique forwarded as True", stub.calls[0][1] is True)


def test_e2_negative_missing_task():
    print("=== E2: missing 'task' -> INPUT_INVALID, never dispatched ===")
    stub = _StubBrain(answer="should never be called")
    r = skill.run("brain_think", {"auto_critique": True}, {"_brain_instance": stub})
    check("missing task -> INPUT_INVALID", r.failure == "INPUT_INVALID", str(r.failure))
    check("stub never invoked", stub.calls == [])


def test_e3_internal_failure_not_swallowed():
    print("=== E3: a real Brain.think exception surfaces, is not swallowed ===")
    stub = _StubBrain(raises=RuntimeError("simulated internal brain failure"))
    r = skill.run("brain_think", {"task": "x"}, {"_brain_instance": stub})
    check("failure surfaces as EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))
    check("no fabricated ok=True", r.ok is False)


def test_stateless_no_memory_changes():
    print("=== stateless: no memory_changes recorded ===")
    stub = _StubBrain(answer="ok")
    r = skill.run("brain_think", {"task": "x"}, {"_brain_instance": stub})
    check("dispatch ok", r.ok, r.failure_detail)
    check("memory_changes empty", not getattr(r, "memory_changes", []) )


if __name__ == "__main__":
    test_e1_happy_path()
    test_e1b_auto_critique_passthrough()
    test_e2_negative_missing_task()
    test_e3_internal_failure_not_swallowed()
    test_stateless_no_memory_changes()
    print("=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — brain_think: mechanical pass-through, failures surface, stateless")

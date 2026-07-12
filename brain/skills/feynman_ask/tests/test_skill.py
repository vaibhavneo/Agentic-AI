"""
Tests for feynman_ask — hermetic, no model, no network. A stub session
injected via context["_session_instance"] stands in for a real
feynman_agent session, per execution_contract.md's documented test seam.

Run: python3 brain/skills/feynman_ask/tests/test_skill.py
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


class _StubSession:
    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.calls = []

    def ask(self, question, session_id):
        self.calls.append((question, session_id))
        if self._raises:
            raise self._raises
        return self._result


def test_e1_happy_path():
    print("=== E1: happy path wraps the stub's result unchanged ===")
    stub = _StubSession(result={"answer": "Because each particle's wavefunction passes "
                                          "through both slits.",
                                "sources": ["Feynman Lectures Vol III"],
                                "chunks_retrieved": 3})
    r = skill.run("feynman_ask", {"question": "Why does the double-slit experiment "
                                              "show interference?"},
                  {"_session_instance": stub})
    check("dispatch ok", r.ok, r.failure_detail)
    check("app == feynman_agent", r.output.get("app") == "feynman_agent")
    check("answer passed through unchanged", r.output.get("answer") == stub._result["answer"])
    check("sources passed through unchanged", r.output.get("sources") == stub._result["sources"])
    check("chunks_retrieved passed through unchanged",
          r.output.get("chunks_retrieved") == 3)


def test_e2_negative_missing_question():
    print("=== E2: missing 'question' -> INPUT_INVALID, never dispatched ===")
    stub = _StubSession(result={"answer": "should never be called", "sources": [],
                                "chunks_retrieved": 0})
    r = skill.run("feynman_ask", {"session_id": "s1"}, {"_session_instance": stub})
    check("missing question -> INPUT_INVALID", r.failure == "INPUT_INVALID", str(r.failure))
    check("stub never invoked", stub.calls == [])


def test_e3_internal_failure_not_swallowed():
    print("=== E3: a real session.ask exception surfaces, is not swallowed ===")
    stub = _StubSession(raises=RuntimeError("simulated tutor failure"))
    r = skill.run("feynman_ask", {"question": "x"}, {"_session_instance": stub})
    check("failure surfaces as EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))
    check("no fabricated ok=True", r.ok is False)


def test_stateless_no_memory_changes():
    print("=== stateless: no memory_changes recorded ===")
    stub = _StubSession(result={"answer": "ok", "sources": [], "chunks_retrieved": 0})
    r = skill.run("feynman_ask", {"question": "x"}, {"_session_instance": stub})
    check("dispatch ok", r.ok, r.failure_detail)
    check("memory_changes empty", not getattr(r, "memory_changes", []))


if __name__ == "__main__":
    test_e1_happy_path()
    test_e2_negative_missing_question()
    test_e3_internal_failure_not_swallowed()
    test_stateless_no_memory_changes()
    print("=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — feynman_ask: mechanical pass-through, failures surface, stateless")

"""
Tests for __SKILL_ID__ — replay every example, assert every evaluation MUST.
Run: python3 <this file>. Exit 1 on failure; print 'ALL PASS' on success.
Conventions (charter §7): idempotent (own your scratch state), print evidence
next to verdicts, ≥1 negative-path check.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ROOT = SKILL_DIR  # __ADJUST: walk up to repo root__
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []
def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond: FAILURES.append(name)

def test_examples_replay():
    """Dispatch each examples/*.json through the runtime; compare outputs."""
    # from aios_core import skill
    for ex_file in sorted((SKILL_DIR / "examples").glob("*.json")):
        ex = json.loads(ex_file.read_text())
        check(f"example {ex_file.name} replays", True, "__implement dispatch+compare__")

def test_evaluation_musts():
    """One test per E-check in evaluation_contract.md, ground truth inline."""
    check("E1 __name__", True, "__implement__")
    check("E2 negative control", True, "__implement__")
    check("E3 bounds", True, "__implement__")

if __name__ == "__main__":
    test_examples_replay()
    test_evaluation_musts()
    print("=" * 50)
    if FAILURES: print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS")

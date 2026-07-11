"""
Deterministic integrity tests for the recursive_planner skill package.
Validates structure, schemas, contract completeness, and portability rules.

Run: python3 brain/skills/recursive_planner/tests/test_skill_package.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PKG = Path(__file__).parent.parent
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_structure():
    print("=== package structure ===")
    required = ["README.md", "skill.md", "input_schema.json", "output_schema.json",
                "execution_contract.md", "memory_contract.md", "evaluation.md"]
    for f in required:
        check(f"{f} exists", (PKG / f).exists())
    check("≥5 examples", len(list((PKG / "examples").glob("*.md"))) >= 5)
    check("tests/ present", (PKG / "tests").is_dir())


def test_schemas():
    print("=== schemas ===")
    inp = json.loads((PKG / "input_schema.json").read_text())
    out = json.loads((PKG / "output_schema.json").read_text())
    check("input: goal/memory_root/criteria required",
          set(inp["required"]) == {"goal", "memory_root", "stability_criteria"})
    check("input: criteria checks are mandatory",
          "check" in inp["properties"]["stability_criteria"]["items"]["required"])
    check("output: 4 status values",
          set(out["properties"]["status"]["enum"]) ==
          {"CONTINUE", "STABLE", "BLOCKED", "ABORTED"})
    check("output: memory update mandatory every cycle",
          out["properties"]["memory_updates"].get("minItems", 0) >= 1)
    check("output: exactly-one atomic task encoded",
          "atomic_task" in out["required"])


def test_execution_contract():
    print("=== execution contract ===")
    text = (PKG / "execution_contract.md").read_text()
    steps = ["LOAD MEMORY", "RETRIEVE", "SELECT NEXT ATOMIC TASK", "EXECUTE",
             "VALIDATE", "COMPRESS", "UPDATE STATE", "DECIDE"]
    positions = [text.find(s) for s in steps]
    check("all 8 protocol steps present", all(p >= 0 for p in positions))
    check("steps appear in canonical order", positions == sorted(positions))


def test_memory_contract():
    print("=== memory contract ===")
    text = (PKG / "memory_contract.md").read_text()
    for section in ["MAY READ", "MAY UPDATE", "IMMUTABLE", "Compression"]:
        check(f"section '{section}' present", section in text)
    check("log append-only", "APPEND-ONLY" in text)
    check("state overwrite semantics", "OVERWRITE" in text)


def test_portability():
    print("=== portability (no model coupling) ===")
    contracts = "".join((PKG / f).read_text() for f in
                        ["execution_contract.md", "memory_contract.md",
                         "input_schema.json", "output_schema.json"])
    banned = re.findall(r"\b(Fable|Opus|Sonnet|Haiku|Anthropic|Claude)\b", contracts)
    check("contracts & schemas name no model/vendor", not banned,
          f"found: {set(banned)}" if banned else "")
    ev = (PKG / "evaluation.md").read_text()
    check("evaluation declares deterministic MUST metrics",
          "deterministic" in ev.lower() and "M1" in ev and "M7" in ev)


def test_versioning():
    print("=== versioning ===")
    readme = (PKG / "README.md").read_text()
    check("semver 1.0.0 declared", "1.0.0" in readme)
    for term in ["Breaking changes", "Compatible changes", "Future extensions"]:
        check(f"'{term}' section present", term in readme)


if __name__ == "__main__":
    test_structure()
    test_schemas()
    test_execution_contract()
    test_memory_contract()
    test_portability()
    test_versioning()
    print(f"\n{'='*56}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — package is contract-complete and portable")

"""
Capability descriptor tests — schema, consistency, honesty checks, REAL
coverage measurement, advisory router, and the P8 boundary (the descriptor
must NOT couple the runtime to any model).

Run: python3 aios_core/tests/test_capability.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aios_core.skill_sdk import capability
from aios_core.skill_sdk.validator import validate_skill

FAILURES: list[str] = []
RP = ROOT / "brain/skills/recursive_planner"
BENCH = ROOT / "aios_core/skill_sdk/benchmark/concept_map"


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_descriptor_loads_and_validates():
    print("=== recursive_planner capability.json loads + validates ===")
    cap = capability.load(RP)
    check("descriptor present", cap is not None)
    check("has the user's fields",
          cap["execution"]["reasoning_level"] == "high"
          and cap["execution"]["estimated_tokens"] == 8000
          and cap["inputs"] == ["mission", "memory", "context"]
          and cap["outputs"] == ["plan", "artifacts", "updated_memory"])
    r = capability.validate(RP)
    check("descriptor VALID", r["ok"] and r["present"],
          str([c["id"] for c in r["checks"] if not c["passed"]]))


def test_optional_absent_is_fine():
    print("=== capability.json is OPTIONAL (absent → valid, no checks) ===")
    tmp = Path(tempfile.mkdtemp(prefix="cap_absent_"))
    r = capability.validate(tmp)
    check("absent descriptor → ok, not present", r["ok"] and not r["present"])
    # a skill with no capability.json still validates via the skill validator
    shutil.rmtree(tmp, ignore_errors=True)
    v = validate_skill(RP, "core", run_tests=False)
    has_v10 = any(c["id"].startswith("V10") for c in v["checks"])
    check("V10 stage folded into skill validator when descriptor present", has_v10)


def test_consistency_enforced():
    print("=== name/version must match the manifest (join key) ===")
    tmp = Path(tempfile.mkdtemp(prefix="cap_mismatch_"))
    shutil.copytree(RP, tmp / "s")
    cap = json.loads((tmp / "s" / "capability.json").read_text())
    cap["version"] = "9.9.9"
    (tmp / "s" / "capability.json").write_text(json.dumps(cap))
    r = capability.validate(tmp / "s")
    check("version mismatch caught (V10c fails)",
          not r["ok"] and any(c["id"] == "V10c" and not c["passed"] for c in r["checks"]))
    shutil.rmtree(tmp, ignore_errors=True)


def test_determinism_honesty_check():
    print("=== deterministic claim must be backed by skill.md (P6/P7) ===")
    tmp = Path(tempfile.mkdtemp(prefix="cap_det_"))
    (tmp / "manifest.json").write_text(json.dumps({"id": "x", "version": "1.0.0"}))
    (tmp / "skill.md").write_text("# x\nThis skill does a thing. No claims about reproducibility.\n")
    (tmp / "capability.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "execution": {"preferred_models": ["m"], "reasoning_level": "low", "estimated_tokens": 1},
        "inputs": ["a"], "outputs": ["b"],
        "quality_requirements": {"min_test_coverage": 0, "deterministic": True,
                                 "requires_human_approval": False}}))
    r = capability.validate(tmp)
    check("unbacked deterministic:true is flagged (V10d fails)",
          any(c["id"] == "V10d" and not c["passed"] for c in r["checks"]))
    shutil.rmtree(tmp, ignore_errors=True)


def test_real_coverage_measurement():
    print("=== REAL stdlib-trace coverage (not asserted — measured) ===")
    # Prove the mechanism on the benchmark skill (small, dedicated test).
    cov = capability.measure_coverage(
        "aios_core.skill_sdk.benchmark.concept_map.driver",
        "python3 aios_core/skill_sdk/benchmark/concept_map/tests/test_skill.py")
    check("coverage measured (real number, not None)", cov["measured"] and cov["pct"] is not None,
          str(cov))
    check("benchmark driver is well-covered (≥80%)", (cov.get("pct") or 0) >= 80, str(cov.get("pct")))
    # And on recursive_planner via its declared target/command.
    q = capability.check_quality_requirements(RP, run_coverage=True)
    v10f = [c for c in q["results"] if c["id"] == "V10f"]
    check("recursive_planner coverage requirement verified", v10f and v10f[0]["passed"],
          v10f[0]["detail"] if v10f else "no V10f")


def test_router_is_advisory_and_data_driven():
    print("=== router reads models FROM descriptors; advisory only ===")
    hint = capability.route([RP])
    check("router surfaces the descriptor's preferred_models",
          hint["preferred_models"] == ["claude-opus", "claude-sonnet", "gpt-5", "gemini"])
    check("router sums estimated tokens", hint["est_tokens"] == 8000)
    check("router respects reasoning floor",
          capability.route([RP], min_reasoning="xhigh")["preferred_models"] == [])
    # human-approval gate surfaces (recursive_planner = false, so empty)
    check("no human-approval gate for recursive_planner", RP.name not in hint["needs_human_approval"])


def test_p8_boundary_preserved():
    print("=== P8: descriptor does NOT couple the runtime to any model ===")
    vendor = re.compile(r"\b(fable|opus|sonnet|haiku|anthropic|gemini|deepseek|openai|gpt-\d)\b", re.I)
    # 1. runtime code still names no vendor
    rt = "".join(f.read_text() for f in (ROOT / "aios_core/runtime").glob("*.py"))
    check("aios_core/runtime/*.py still vendor-clean", not vendor.search(rt))
    # 2. capability.py itself hardcodes no model literal (reads them from data)
    cap_src = (ROOT / "aios_core/skill_sdk/capability.py").read_text()
    check("capability.py names no model in code (router is data-driven)",
          not vendor.search(cap_src))
    # 3. the dispatcher never imports capability (execution path is unaware of it)
    disp = (ROOT / "aios_core/runtime/dispatcher.py").read_text()
    check("dispatcher does not import capability", "capability" not in disp)


if __name__ == "__main__":
    test_descriptor_loads_and_validates()
    test_optional_absent_is_fine()
    test_consistency_enforced()
    test_determinism_honesty_check()
    test_real_coverage_measurement()
    test_router_is_advisory_and_data_driven()
    test_p8_boundary_preserved()
    print(f"\n{'='*62}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — capability descriptors: advisory, verified, P8-safe")

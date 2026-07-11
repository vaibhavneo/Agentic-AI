"""
Skill SDK regression suite — validator, quality score, template property,
and the Part-10 benchmark parity (automated so BENCHMARK_REPORT.md can't rot).

Run: python3 aios_core/tests/test_skill_sdk.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aios_core.skill_sdk import validate_skill, score_skill

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_template_property():
    print("=== template: fails EXACTLY the two placeholder checks ===")
    r = validate_skill(ROOT / "templates/skill", "full")
    fails = sorted(c["id"] for c in r["checks"] if not c["passed"])
    check("unfilled template fails only V2c+V2f", fails == ["V2c", "V2f"], str(fails))
    check("template test scaffold itself executes (V7b)",
          any(c["id"] == "V7b" and c["passed"] for c in r["checks"]))


def test_recreation_is_valid_full_profile():
    print("=== benchmark recreation: full-profile VALID, quality high ===")
    d = ROOT / "aios_core/skill_sdk/benchmark/concept_map"
    r = validate_skill(d, "full", run_tests=True)
    check("recreation VALID (all checks)", r["ok"],
          str([c["id"] for c in r["checks"] if not c["passed"]]))
    q = score_skill(d)
    check("recreation quality ≥ 85 (SDK bar)", q["total"] >= 85, q["total"])


def test_quality_discriminates():
    print("=== quality score discriminates (an eval everything aces tests nothing) ===")
    scores = {}
    for d in sorted((ROOT / "brain/skills").iterdir()):
        if (d / "manifest.json").exists():
            scores[d.name] = score_skill(d)["total"]
    scores["__recreation__"] = score_skill(
        ROOT / "aios_core/skill_sdk/benchmark/concept_map")["total"]
    spread = max(scores.values()) - min(scores.values())
    check("score spread ≥ 20 points across library", spread >= 20,
          f"min={min(scores.values())} max={max(scores.values())}")
    check("flagship outscores minimal legacy skills",
          scores["recursive_planner"] > scores["retrieve_context"])


def test_legacy_library_core_valid():
    print("=== legacy library: every skill passes CORE profile ===")
    for d in sorted((ROOT / "brain/skills").iterdir()):
        if (d / "manifest.json").exists():
            r = validate_skill(d, "core", run_tests=False)
            check(f"{d.name} core-valid", r["ok"],
                  str([c["id"] for c in r["checks"] if not c["passed"]]))


def test_benchmark_behavior_parity():
    print("=== Part-10 parity: recreation set-equals original on live store ===")
    from aios_core.skill_sdk.benchmark.concept_map.driver import run as recreated
    from packs.ai_engineering.drivers.concept_map import run as original
    for case in ({"min_confidence": 0.0}, {"min_confidence": 0.6},
                 {"name_contains": "rag"}):
        o, r = original(dict(case), {}), recreated(dict(case), {})
        same = ({n["name"] for n in o["nodes"]} == {n["name"] for n in r["nodes"]}
                and sorted(map(json.dumps, o["edges"])) == sorted(map(json.dumps, r["edges"]))
                and o["n"] == r["n"])
        check(f"set-parity {case}", same)


def test_validator_negative_path():
    print("=== validator negative control: empty dir is INVALID ===")
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp(prefix="sdk_neg_"))
    r = validate_skill(tmp, "full", run_tests=False)
    check("empty dir → INVALID with structure failures",
          not r["ok"] and any(c["id"] == "V1a" and not c["passed"] for c in r["checks"]))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_template_property()
    test_recreation_is_valid_full_profile()
    test_quality_discriminates()
    test_legacy_library_core_valid()
    test_benchmark_behavior_parity()
    test_validator_negative_path()
    print(f"\n{'='*62}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — Skill SDK validates, scores, and reproduces skills")

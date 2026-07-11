"""
Skill Capability Descriptor — advisory metadata ABOVE the execution manifest.

WHY THIS IS SEPARATE FROM manifest.json (the load-bearing design decision):
  - manifest.json is the EXECUTION contract. The dispatcher reads it. It MUST
    stay model-agnostic (PROJECT_CHARTER.md P8: no runtime-parsed artifact names
    a model/vendor; test-enforced over aios_core/runtime/*.py).
  - capability.json is ADVISORY metadata for a capability ROUTER / SCHEDULER /
    marketplace that sits ABOVE the dispatcher. The dispatcher NEVER reads it.
    It informs an operator's/orchestrator's CHOICE OF ADAPTER — it never changes
    skill behavior. Model names here are DATA (a config list an author supplies),
    exactly like MODEL_EXECUTION_GUIDE.md names models as documentation. This
    module reads model names FROM descriptors; it hardcodes none (extends the P8
    guarantee to the router — test-enforced in test_capability.py).

WHAT IT ADDS (all additive, none duplicating the manifest):
  - execution routing hints: preferred_models, reasoning_level, estimated_tokens
  - semantic I/O roles (mission/memory/context → plan/artifacts/updated_memory)
    — an ontology layer above the JSON schemas, for capability matching
  - quality_requirements: min_test_coverage, deterministic, requires_human_approval

Charter P6 (evaluator before trust): checkable claims are VERIFIED, not asserted.
`deterministic` is cross-checked against skill.md; `min_test_coverage` is a REAL
stdlib-`trace` line-coverage measurement (opt-in — it runs a test command).

CLI: python3 -m aios_core.skill_sdk.capability <skill_dir> [--coverage]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from ..runtime.validator import validate as _schema_validate

_ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_FILE = "capability.json"
REASONING_LEVELS = ["low", "medium", "high", "xhigh"]

# Structural schema (validated with the SDK's own JSON-Schema-subset validator).
CAPABILITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "version", "execution", "inputs", "outputs",
                 "quality_requirements"],
    "properties": {
        "name": {"type": "string"},
        "version": {"type": "string"},
        "execution": {
            "type": "object", "additionalProperties": False,
            "required": ["preferred_models", "reasoning_level", "estimated_tokens"],
            "properties": {
                "preferred_models": {"type": "array", "items": {"type": "string"}},
                "reasoning_level": {"enum": REASONING_LEVELS},
                "estimated_tokens": {"type": "integer", "minimum": 0},
            },
        },
        "inputs": {"type": "array", "items": {"type": "string"}},
        "outputs": {"type": "array", "items": {"type": "string"}},
        "quality_requirements": {
            "type": "object", "additionalProperties": False,
            "required": ["min_test_coverage", "deterministic", "requires_human_approval"],
            "properties": {
                "min_test_coverage": {"type": "integer", "minimum": 0, "maximum": 100},
                "deterministic": {"type": "boolean"},
                "requires_human_approval": {"type": "boolean"},
                "coverage_target": {"type": "string"},   # optional: module to measure
                "coverage_command": {"type": "string"},   # optional: how to exercise it
            },
        },
    },
}


def load(skill_dir) -> dict | None:
    p = Path(skill_dir) / CAPABILITY_FILE
    return json.loads(p.read_text()) if p.exists() else None


def _check(checks, cid, name, ok, detail=""):
    checks.append({"id": cid, "name": name, "passed": bool(ok), "detail": detail})


def validate(skill_dir) -> dict:
    """Fast structural + consistency validation (no coverage run). A skill with
    no capability.json returns ok=True, present=False (descriptor is OPTIONAL)."""
    d = Path(skill_dir)
    cap = load(d)
    if cap is None:
        return {"ok": True, "present": False, "checks": []}

    checks: list[dict] = []
    errs = _schema_validate(cap, CAPABILITY_SCHEMA)
    _check(checks, "V10a", "capability.json conforms to schema", not errs, "; ".join(errs))

    # consistency with the manifest (name/version are the join key)
    mf = d / "manifest.json"
    if mf.exists():
        m = json.loads(mf.read_text())
        _check(checks, "V10b", "capability.name == manifest.id",
               cap.get("name") == m.get("id"), f"{cap.get('name')} vs {m.get('id')}")
        _check(checks, "V10c", "capability.version == manifest.version",
               cap.get("version") == m.get("version"),
               f"{cap.get('version')} vs {m.get('version')}")

    # honesty: a deterministic:true claim must be backed by skill.md (P6/P7)
    det_claim = cap.get("quality_requirements", {}).get("deterministic")
    smd = (d / "skill.md").read_text().lower() if (d / "skill.md").exists() else ""
    if det_claim is True:
        backed = "determin" in smd
        _check(checks, "V10d", "deterministic claim backed by skill.md Determinism section",
               backed, "" if backed else "skill.md makes no determinism statement")

    _check(checks, "V10e", "reasoning_level is a known level",
           cap.get("execution", {}).get("reasoning_level") in REASONING_LEVELS)
    return {"ok": all(c["passed"] for c in checks), "present": True, "checks": checks}


# ── Real coverage measurement (stdlib trace; no new dependency) ─────────────

_COVER_LINE = re.compile(r"^\s*(\d+|>{6}):")   # trace --count annotation


def measure_coverage(target_module: str, command: str, cwd: Path | None = None) -> dict:
    """Run `command` under `python -m trace --count`, then compute LINE coverage
    of `target_module` from the annotated .cover file. Real, deterministic,
    stdlib-only. `command` is the shell command that exercises the module (e.g.
    the skill's test file). Returns {pct, covered, coverable, measured:bool}."""
    cwd = Path(cwd or _ROOT)
    with tempfile.TemporaryDirectory() as td:
        parts = command.split()
        if parts[:2] == ["python3", ""]:
            parts = parts[1:]
        # normalize `python3 X` → `python3 -m trace --count --coverdir td X`
        script = [p for p in parts if p not in ("python3", "python")]
        cmd = [sys.executable, "-m", "trace", "--count", f"--coverdir={td}"] + script
        subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=600)
        # find the target module's .cover file
        target_path = _ROOT / (target_module.replace(".", "/") + ".py")
        cover = list(Path(td).glob(f"*{target_path.stem}.cover"))
        if not cover:
            return {"pct": None, "measured": False,
                    "detail": f"no .cover produced for {target_module} (was it imported?)"}
        executed = coverable = 0
        for line in cover[0].read_text().splitlines():
            m = _COVER_LINE.match(line)
            if not m:
                continue
            coverable += 1
            if m.group(1) != ">>>>>>":
                executed += 1
        pct = round(100 * executed / coverable, 1) if coverable else 0.0
        return {"pct": pct, "covered": executed, "coverable": coverable, "measured": True}


def check_quality_requirements(skill_dir, run_coverage: bool = False) -> dict:
    """Verify the descriptor's checkable quality claims. Coverage is OPT-IN
    (it runs a test command) — mirrors the platform's fast-check vs on-demand-
    deep-check split. Returns per-requirement pass/fail with evidence."""
    d = Path(skill_dir)
    cap = load(d)
    if cap is None:
        return {"present": False, "results": []}
    qr = cap["quality_requirements"]
    results = validate(d)["checks"]

    if run_coverage and qr.get("coverage_target") and qr.get("coverage_command"):
        cov = measure_coverage(qr["coverage_target"], qr["coverage_command"])
        if cov["measured"]:
            _check(results, "V10f",
                   f"measured coverage ≥ min_test_coverage ({qr['min_test_coverage']}%)",
                   cov["pct"] >= qr["min_test_coverage"],
                   f"measured {cov['pct']}% ({cov['covered']}/{cov['coverable']} lines)")
        else:
            _check(results, "V10f", "coverage measurable", False, cov["detail"])
    elif run_coverage:
        _check(results, "V10f", "coverage_target + coverage_command declared", False,
               "min_test_coverage set but no target/command to measure it — unverifiable")

    return {"present": True, "ok": all(c["passed"] for c in results), "results": results}


# ── Advisory router (reads models FROM descriptors — hardcodes none) ────────

def route(skill_dirs, min_reasoning: str | None = None) -> dict:
    """ADVISORY ONLY. Given skills' capability descriptors, suggest which
    models an orchestrator might use and flag human-approval gates. Returns a
    hint; the dispatcher/runtime never consults this. Model names come entirely
    from the descriptors (no vendor literal appears in this function)."""
    order = {lvl: i for i, lvl in enumerate(REASONING_LEVELS)}
    hint = {"preferred_models": [], "needs_human_approval": [], "est_tokens": 0,
            "skipped": []}
    seen: list[str] = []
    for sd in skill_dirs:
        cap = load(sd)
        if not cap:
            hint["skipped"].append(str(sd)); continue
        ex = cap["execution"]
        if min_reasoning and order[ex["reasoning_level"]] < order[min_reasoning]:
            continue
        for mdl in ex["preferred_models"]:
            if mdl not in seen:
                seen.append(mdl)
        hint["est_tokens"] += ex["estimated_tokens"]
        if cap["quality_requirements"].get("requires_human_approval"):
            hint["needs_human_approval"].append(cap["name"])
    hint["preferred_models"] = seen
    return hint


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    if "--coverage" in sys.argv:
        print(json.dumps(check_quality_requirements(target, run_coverage=True), indent=1))
    else:
        r = validate(target)
        for c in r["checks"]:
            print(f"  [{'OK ' if c['passed'] else 'FAIL'}] {c['id']} {c['name']}  {c['detail']}")
        print("present" if r["present"] else "absent (optional)",
              "· VALID" if r["ok"] else "· INVALID")

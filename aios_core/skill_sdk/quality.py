"""
Skill SDK — objective quality score (spec: SKILL_VALIDATION.md §Quality).

Eight weighted categories, each 0.0–1.0, deterministic heuristics over the
skill's files (no LLM judging — charter D10 applied to skill quality):

  completeness 20 · documentation 15 · testing 15 · determinism 10 ·
  memory_safety 10 · portability 10 · runtime_compatibility 10 ·
  maintainability 10                                (total 100)

CLI: python3 -m aios_core.skill_sdk.quality <skill_dir>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .validator import (FULL_FILES, FULL_DIRS, SKILL_MD_FULL, VENDOR,
                        PLACEHOLDER, SEMVER, validate_skill)

WEIGHTS = {"completeness": 20, "documentation": 15, "testing": 15,
           "determinism": 10, "memory_safety": 10, "portability": 10,
           "runtime_compatibility": 10, "maintainability": 10}


def _frac(n, d):
    return (n / d) if d else 0.0


def score_skill(skill_dir) -> dict:
    d = Path(skill_dir)
    cats: dict[str, float] = {}
    manifest = {}
    try:
        manifest = json.loads((d / "manifest.json").read_text())
    except Exception:
        pass

    # completeness — canonical files present
    present = sum((d / f).exists() for f in FULL_FILES) + \
              sum((d / x).is_dir() for x in FULL_DIRS)
    cats["completeness"] = _frac(present, len(FULL_FILES) + len(FULL_DIRS))

    # documentation — mandatory sections + no placeholders + purpose real
    doc = 0.0
    if (d / "skill.md").exists():
        smd = (d / "skill.md").read_text()
        doc += 0.5 * _frac(sum(s.lower() in smd.lower() for s in SKILL_MD_FULL),
                           len(SKILL_MD_FULL))
        doc += 0.2 * (not PLACEHOLDER.search(smd))
    if (d / "README.md").exists():
        doc += 0.2 * (not PLACEHOLDER.search((d / "README.md").read_text()))
    doc += 0.1 * bool(str(manifest.get("purpose", "")).strip() and
                      not PLACEHOLDER.search(str(manifest.get("purpose", ""))))
    cats["documentation"] = min(doc, 1.0)

    # testing — files exist, pass, and include a negative-path signal
    t = 0.0
    tests = sorted((d / "tests").glob("test_*.py")) if (d / "tests").is_dir() else []
    if tests:
        t += 0.3
        v = validate_skill(d, "full", run_tests=True)
        t += 0.5 * all(c["passed"] for c in v["checks"] if c["id"] == "V7b")
        blob = "".join(x.read_text() for x in tests)
        t += 0.2 * bool(re.search(r"negative|gibberish|invalid|failure|FAIL", blob))
    cats["testing"] = min(t, 1.0)

    # determinism — declared and consistent with runtime type
    det = 0.0
    smd = (d / "skill.md").read_text() if (d / "skill.md").exists() else ""
    rt = (manifest.get("execution") or {}).get("runtime", {}).get("type")
    if "determin" in smd.lower():
        det += 0.6
    if rt == "python":
        det += 0.4                       # python drivers are reproducible by construction
    elif rt == "agent":
        outs = manifest.get("outputs") or {}
        det += 0.4 * bool(outs)          # schema-enforced output is the agent-side guarantee
    cats["determinism"] = min(det, 1.0)

    # memory_safety — declared block, contract doc if it writes, no bare wildcard
    mem = manifest.get("memory") or {}
    ms = 0.4 * bool(mem)
    writes = (mem.get("write") or []) + (mem.get("append_only") or [])
    if writes:
        ms += 0.3 * (d / "memory_contract.md").exists()
        ms += 0.3 * ("*" not in (mem.get("write") or []))
    else:
        ms += 0.6                        # stateless = safest
    cats["memory_safety"] = min(ms, 1.0)

    # portability — no vendor names in CODE (drivers/tests) or the manifest.
    # Prose (.md) is exempt: docs may legitimately name models as examples of
    # interchangeability ("Fable, Opus, a human — anything callable"), which is
    # the opposite of coupling; only executable surfaces must stay agnostic (P8).
    blob = json.dumps(manifest)
    for f in d.rglob("*.py"):
        blob += f.read_text(errors="ignore")
    cats["portability"] = 0.0 if VENDOR.search(blob) else 1.0

    # runtime_compatibility — registers + entrypoint/deps resolve (V2/V8 checks)
    v = validate_skill(d, "core", run_tests=False)
    rc_ids = {"V2a", "V2b", "V2d", "V2e", "V8a", "V8c"}
    rc = [c for c in v["checks"] if c["id"] in rc_ids]
    cats["runtime_compatibility"] = _frac(sum(c["passed"] for c in rc), len(rc)) if rc else 0.0

    # maintainability — changelog discipline + bounded file sizes + semver
    m = 0.0
    if (d / "CHANGELOG.md").exists():
        m += 0.4
        top = re.search(r"^## (\d+\.\d+\.\d+)", (d / "CHANGELOG.md").read_text(), re.M)
        m += 0.3 * bool(top and top.group(1) == str(manifest.get("version")))
    m += 0.2 * bool(SEMVER.match(str(manifest.get("version", ""))))
    big = [f.name for f in d.rglob("*") if f.is_file() and f.suffix in (".py", ".md")
           and len(f.read_text(errors="ignore").splitlines()) > 400]
    m += 0.1 * (not big)
    cats["maintainability"] = min(m, 1.0)

    total = round(sum(cats[k] * WEIGHTS[k] for k in WEIGHTS), 1)
    return {"skill": d.name, "total": total, "max": 100,
            "categories": {k: round(v, 2) for k, v in cats.items()},
            "weights": WEIGHTS}


if __name__ == "__main__":
    r = score_skill(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(json.dumps(r, indent=1))

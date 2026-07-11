"""
Skill SDK — automated skill validator (SKILL_VALIDATION.md is the spec).

validate_skill(skill_dir, profile) runs the 9-stage pipeline:
  V1 structure · V2 manifest · V3 contracts · V4 schemas · V5 documentation
  · V6 examples · V7 test execution · V8 compatibility · V9 versioning

Profiles:
  "full" — the canonical 11-file layout (templates/skill/). REQUIRED for all
           NEW skills.
  "core" — the pre-SDK minimal layout (manifest.json + skill.md + README.md).
           Exists so the 2026-07 legacy library can be graded without
           rewriting history; legacy skills are migration debt, tracked in
           the quality score, not silently passed.

Deterministic, stdlib-only (charter P6/P8). Exit codes for CLI use:
  python3 -m aios_core.skill_sdk.validator <skill_dir> [core|full]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

FULL_FILES = ["README.md", "manifest.json", "skill.md", "execution_contract.md",
              "memory_contract.md", "evaluation_contract.md", "input_schema.json",
              "output_schema.json", "CHANGELOG.md"]
FULL_DIRS = ["examples", "tests"]
CORE_FILES = ["manifest.json", "skill.md", "README.md"]

MANIFEST_KEYS = {"id", "name", "version", "description", "purpose", "tags",
                 "inputs", "outputs", "memory", "execution", "dependencies",
                 "evaluation"}          # 12 keys — purpose IS required for SDK skills
SKILL_MD_MANDATORY = ["Purpose", "Inputs", "Outputs"]
SKILL_MD_FULL = SKILL_MD_MANDATORY + ["Business problem", "Determinism",
                                      "Hidden-assumption audit", "Precondition"]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
VENDOR = re.compile(r"\b(fable|opus|sonnet|haiku|anthropic|gemini|deepseek|openai|gpt-\d)\b", re.I)
PLACEHOLDER = re.compile(r"__[A-Za-z0-9 _.:→|()/-]{2,}__")


def _c(checks, cid, name, passed, detail=""):
    checks.append({"id": cid, "name": name, "passed": bool(passed), "detail": detail})


def _read_json(p: Path):
    try:
        return json.loads(p.read_text()), None
    except Exception as e:
        return None, str(e)


def validate_skill(skill_dir, profile: str = "full",
                   run_tests: bool = True) -> dict:
    d = Path(skill_dir)
    checks: list[dict] = []
    manifest = None

    # ── V1 structure ────────────────────────────────────────────────────────
    required = FULL_FILES if profile == "full" else CORE_FILES
    missing = [f for f in required if not (d / f).exists()]
    _c(checks, "V1a", f"required files present ({profile} profile)",
       not missing, f"missing: {missing}" if missing else "")
    if profile == "full":
        mdirs = [x for x in FULL_DIRS if not (d / x).is_dir()]
        _c(checks, "V1b", "examples/ and tests/ dirs present", not mdirs, str(mdirs))

    # ── V2 manifest ─────────────────────────────────────────────────────────
    if (d / "manifest.json").exists():
        manifest, err = _read_json(d / "manifest.json")
        _c(checks, "V2a", "manifest parses", manifest is not None, err or "")
        if manifest:
            miss = MANIFEST_KEYS - set(manifest)
            _c(checks, "V2b", "manifest has all 12 keys (incl. purpose)",
               not miss, f"missing: {sorted(miss)}")
            _c(checks, "V2c", "id matches folder name",
               manifest.get("id") == d.name, f"{manifest.get('id')} vs {d.name}")
            _c(checks, "V2d", "version is semver",
               bool(SEMVER.match(str(manifest.get("version", "")))))
            rt = (manifest.get("execution") or {}).get("runtime", {})
            _c(checks, "V2e", "runtime type declared (python|agent)",
               rt.get("type") in ("python", "agent"), str(rt.get("type")))
            _c(checks, "V2f", "no unresolved __placeholders__ in manifest",
               not PLACEHOLDER.search(json.dumps(manifest)))
    else:
        _c(checks, "V2a", "manifest parses", False, "manifest.json absent")

    # ── V3 contracts ────────────────────────────────────────────────────────
    if manifest:
        steps = (manifest.get("execution") or {}).get("steps", [])
        _c(checks, "V3a", "execution steps declared", len(steps) >= 1, f"n={len(steps)}")
        if profile == "full":
            ec = d / "execution_contract.md"
            if ec.exists():
                ect = ec.read_text()
                covered = [s for s in steps if s and s.split("__")[0].strip(" _") and s in ect]
                _c(checks, "V3b", "every manifest step appears in execution_contract.md",
                   len(covered) == len(steps) or PLACEHOLDER.search(ect) is not None,
                   f"{len(covered)}/{len(steps)}")
                _c(checks, "V3c", "failure handling section present",
                   "Failure handling" in ect)
            mem = manifest.get("memory", {})
            writes = (mem.get("write") or []) + (mem.get("append_only") or [])
            if writes:
                _c(checks, "V3d", "memory_contract.md explains declared writes",
                   (d / "memory_contract.md").exists())

    # ── V4 schemas ──────────────────────────────────────────────────────────
    for role in ("input", "output"):
        sp = d / f"{role}_schema.json"
        inline = manifest and "schema_inline" in (manifest.get(f"{role}s") or {})
        if sp.exists():
            sch, err = _read_json(sp)
            ok = sch is not None and sch.get("type") == "object"
            _c(checks, f"V4-{role}", f"{role}_schema valid (parses, type=object)", ok, err or "")
        elif inline:
            _c(checks, f"V4-{role}", f"{role} schema inline in manifest", True)
        elif profile == "full":
            _c(checks, f"V4-{role}", f"{role} schema present", False, "neither file nor inline")

    # ── V5 documentation completeness ───────────────────────────────────────
    if (d / "skill.md").exists():
        smd = (d / "skill.md").read_text()
        need = SKILL_MD_FULL if profile == "full" else SKILL_MD_MANDATORY
        missing_sec = [s for s in need if s.lower() not in smd.lower()]
        _c(checks, "V5a", f"skill.md has mandatory sections ({len(need)})",
           not missing_sec, f"missing: {missing_sec}")
    if profile == "full" and (d / "CHANGELOG.md").exists() and manifest:
        _c(checks, "V5b", "CHANGELOG mentions current version",
           str(manifest.get("version")) in (d / "CHANGELOG.md").read_text())

    # ── V6 examples ─────────────────────────────────────────────────────────
    if profile == "full":
        exs = sorted((d / "examples").glob("*.json")) if (d / "examples").is_dir() else []
        _c(checks, "V6a", "≥1 example", len(exs) >= 1, f"n={len(exs)}")
        neg = any("negative" in e.name or
                  "expected_failure" in e.read_text() for e in exs)
        _c(checks, "V6b", "≥1 negative example", neg)
        bad = [e.name for e in exs if _read_json(e)[0] is None or
               "inputs" not in (_read_json(e)[0] or {})]
        _c(checks, "V6c", "examples parse and carry 'inputs'", not bad, str(bad))

    # ── V7 test execution ───────────────────────────────────────────────────
    if profile == "full" and run_tests:
        tests = sorted((d / "tests").glob("test_*.py")) if (d / "tests").is_dir() else []
        _c(checks, "V7a", "≥1 test file", len(tests) >= 1)
        for t in tests:
            r = subprocess.run([sys.executable, str(t)], capture_output=True,
                               timeout=300, cwd=str(_ROOT))
            _c(checks, "V7b", f"{t.name} exits 0", r.returncode == 0,
               (r.stdout or r.stderr)[-150:].decode(errors="ignore").strip())

    # ── V8 compatibility ────────────────────────────────────────────────────
    if manifest:
        rt = (manifest.get("execution") or {}).get("runtime", {})
        if rt.get("type") == "python" and rt.get("entrypoint") and \
           not PLACEHOLDER.search(rt.get("entrypoint", "")):
            mod = rt["entrypoint"].split(":")[0]
            try:
                import importlib
                if str(_ROOT) not in sys.path:
                    sys.path.insert(0, str(_ROOT))
                if str(_ROOT / "brain") not in sys.path:
                    sys.path.insert(0, str(_ROOT / "brain"))
                m = importlib.import_module(mod)
                fn = getattr(m, rt["entrypoint"].split(":")[1], None)
                _c(checks, "V8a", "entrypoint importable + callable", callable(fn))
                if callable(fn):
                    src = Path(m.__file__).read_text()
                    _c(checks, "V8b", "driver names no model/vendor (P8)",
                       not VENDOR.search(src),
                       str(set(VENDOR.findall(src))) if VENDOR.search(src) else "")
            except Exception as e:
                _c(checks, "V8a", "entrypoint importable + callable", False, str(e)[:120])
        for dep in manifest.get("dependencies", []):
            try:
                from aios_core.runtime.registry import Registry
                Registry().get_manifest(dep["id"], dep.get("version", "*"))
                _c(checks, "V8c", f"dependency '{dep['id']}' resolves", True)
            except Exception as e:
                _c(checks, "V8c", f"dependency '{dep['id']}' resolves",
                   bool(dep.get("optional")), str(e)[:100])

    # ── V9 versioning rules ────────────────────────────────────────────────
    if manifest and (d / "CHANGELOG.md").exists():
        top = re.search(r"^## (\d+\.\d+\.\d+)", (d / "CHANGELOG.md").read_text(), re.M)
        _c(checks, "V9a", "CHANGELOG top entry == manifest version",
           bool(top) and top.group(1) == str(manifest.get("version")),
           f"{top.group(1) if top else None} vs {manifest.get('version')}")

    # ── V10 capability descriptor (OPTIONAL — only if capability.json exists) ─
    # Advisory metadata above the manifest; the dispatcher never reads it.
    # Absent capability.json is fine (returns no checks). See capability.py.
    from .capability import validate as _validate_capability
    cap = _validate_capability(d)
    if cap["present"]:
        checks.extend(cap["checks"])

    ok = all(c["passed"] for c in checks)
    return {"ok": ok, "profile": profile, "skill": d.name, "checks": checks,
            "passed": sum(c["passed"] for c in checks), "total": len(checks)}


def print_report(result: dict) -> None:
    print(f"skill={result['skill']} profile={result['profile']} "
          f"{result['passed']}/{result['total']}")
    for c in result["checks"]:
        mark = "OK " if c["passed"] else "FAIL"
        print(f"  [{mark}] {c['id']:6s} {c['name']}  {c['detail']}")
    print("VALID" if result["ok"] else "INVALID")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    prof = sys.argv[2] if len(sys.argv) > 2 else "full"
    r = validate_skill(target, prof)
    print_report(r)
    sys.exit(0 if r["ok"] else 1)

"""
Repository self-consistency validator — keeps the human-written truth in
memory/ and the *.md handoff docs from drifting away from the machine truth in
registry.json / manifests / the runtime spec / model adapters (charter P6:
validate the doc against the code, not by eye). A sibling of
docs/validate_api_reference.py; run it after editing any of the sources below.

Run: python3 docs/validate_repo_consistency.py   (exit 1 on any mismatch)

Checks (each cross-references TWO independent sources of truth):
  1. skill count in memory/state.md == number of skills in brain/skills/registry.json
  2. latest decision number in memory/decisions.md == the highest ADR referenced
     in HANDOFF.md (the handoff must name the current decision frontier)
  3. every test suite documented in IMPLEMENTATION_PLAYBOOK.md §V exists on disk,
     and their count == the "N/N test suites" claim in memory/state.md
  4. the REQUIRED manifest keys documented in brain/runtime/runtime.md ==
     aios_core.skill_sdk.validator.MANIFEST_KEYS (the code that enforces them)
  5. no stale/wildcard model references remain in any real capability.json —
     every preferred_models entry resolves to an adapter in model_adapters/,
     and none is a wildcard ('*', '-latest' alias, or unfilled __placeholder__)

Each check is a pure function of already-parsed inputs so it can be unit-tested
with fixtures (docs/tests/test_repo_consistency.py); main() does the file I/O.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAIL: list[str] = []


def ck(name, result):
    ok, detail = result
    print(f"  [{'OK' if ok else 'FAIL'}] {name}  {detail}")
    if not ok:
        FAIL.append(name)


# ── Check 1: skill count ─────────────────────────────────────────────────────
def check_skill_count(state_md: str, registry: dict):
    """state.md's skill_library row claims 'N skills'; must equal len(registry)."""
    m = None
    for line in state_md.splitlines():
        if "skill_library" in line:
            m = re.search(r"(\d+)\s+skills", line)
            if m:
                break
    if m is None:
        m = re.search(r"(\d+)\s+skills", state_md)
    if m is None:
        return False, "no 'N skills' claim found in state.md"
    documented = int(m.group(1))
    actual = len(registry.get("skills", []))
    return documented == actual, f"state.md={documented} registry.json={actual}"


# ── Check 2: latest decision number ──────────────────────────────────────────
def _max_decision(text: str):
    nums = [int(n) for n in re.findall(r"\bD(\d+)\b", text)]
    return max(nums) if nums else None


def check_decision_number(decisions_md: str, handoff_md: str):
    """Highest D<n> in decisions.md must equal the highest D<n> HANDOFF cites."""
    latest = _max_decision(decisions_md)
    handoff = _max_decision(handoff_md)
    if latest is None:
        return False, "no D<n> decisions found in decisions.md"
    if handoff is None:
        return False, "no D<n> reference found in HANDOFF.md"
    return latest == handoff, f"decisions.md latest=D{latest} HANDOFF.md=D{handoff}"


# ── Check 3: documented test suites ──────────────────────────────────────────
def parse_documented_suites(playbook_md: str):
    """Test-suite paths inside IMPLEMENTATION_PLAYBOOK.md §V, order-preserved.

    Anchored to the '## §V' heading (a prose mention of the section name also
    exists earlier in the doc, so a plain substring search would miss)."""
    m = re.search(r"^#+\s*§V\b.*$", playbook_md, re.M)
    section = playbook_md[m.start():] if m else playbook_md
    nxt = re.search(r"\n#+\s", section[3:])
    if nxt:
        section = section[: nxt.start() + 3]
    seen: list[str] = []
    for p in re.findall(r"python3\s+(\S+\.py)", section):
        if p not in seen:
            seen.append(p)
    return seen


def check_test_suite_count(playbook_md: str, state_md: str, exists_fn):
    """Every §V suite exists (via exists_fn) and count == state.md's N/N claim."""
    suites = parse_documented_suites(playbook_md)
    missing = [p for p in suites if not exists_fn(p)]
    m = re.search(r"(\d+)\s*/\s*(\d+)\s+test suites", state_md)
    claim = int(m.group(2)) if m else None
    ok = (not missing) and (claim is not None) and (claim == len(suites))
    return ok, f"documented={len(suites)} state.md claim={claim} missing={missing}"


# ── Check 4: manifest required keys ──────────────────────────────────────────
def parse_runtime_manifest_keys(runtime_md: str):
    """The '(id, name, ...)' list on the LOAD_MANIFEST line of runtime.md."""
    m = re.search(r"manifest keys present\s*\(([^)]+)\)", runtime_md)
    if m is None:
        return None
    return {k.strip() for k in m.group(1).split(",") if k.strip()}


def check_manifest_keys(runtime_md: str, code_keys):
    doc = parse_runtime_manifest_keys(runtime_md)
    if doc is None:
        return False, "could not parse manifest keys from runtime.md"
    code = set(code_keys)
    ok = doc == code
    detail = f"runtime.md={len(doc)} keys, validator.MANIFEST_KEYS={len(code)} keys"
    if not ok:
        detail += (f" | only_in_doc={sorted(doc - code)}"
                   f" only_in_code={sorted(code - doc)}")
    return ok, detail


# ── Check 5: stale model-adapter wildcards ───────────────────────────────────
def adapter_tokens(adapter_filenames):
    """Family keywords per adapter file, e.g. Claude_Opus.md -> {claude, opus}."""
    toks: set[str] = set()
    for fn in adapter_filenames:
        if fn.lower() == "readme.md":
            continue
        stem = fn.rsplit(".", 1)[0]
        toks |= {t.lower() for t in re.split(r"[_\-]", stem) if t}
    return toks


def classify_model_ref(ref: str, tokens):
    if "*" in ref or ref.endswith("-latest") or re.match(r"^__.*__$", ref):
        return "wildcard"
    parts = {t.lower() for t in re.split(r"[_\-]", ref) if t}
    return "ok" if parts & tokens else "stale"


def check_no_stale_adapter_wildcards(capability_models, adapter_filenames):
    """capability_models: list of (source, model_ref). All must resolve to an
    adapter and be pinned (no wildcards)."""
    tokens = adapter_tokens(adapter_filenames)
    problems = []
    for src, ref in capability_models:
        verdict = classify_model_ref(ref, tokens)
        if verdict != "ok":
            problems.append(f"{src}:{ref}({verdict})")
    return (not problems), ("none" if not problems else "; ".join(problems))


# ── Wiring ───────────────────────────────────────────────────────────────────
def _collect_capability_models():
    """Every preferred_models entry from real (non-template) capability.json."""
    out = []
    for cap in ROOT.rglob("capability.json"):
        rel = cap.relative_to(ROOT).as_posix()
        if rel.startswith("templates/"):
            continue  # template placeholders are intentional
        data = json.loads(cap.read_text())
        for ref in data.get("execution", {}).get("preferred_models", []):
            out.append((rel, ref))
    return out


def main():
    state = (ROOT / "memory/state.md").read_text()
    registry = json.loads((ROOT / "brain/skills/registry.json").read_text())
    decisions = (ROOT / "memory/decisions.md").read_text()
    handoff = (ROOT / "HANDOFF.md").read_text()
    playbook = (ROOT / "IMPLEMENTATION_PLAYBOOK.md").read_text()
    runtime_md = (ROOT / "brain/runtime/runtime.md").read_text()

    from aios_core.skill_sdk.validator import MANIFEST_KEYS

    adapter_files = [p.name for p in (ROOT / "model_adapters").glob("*.md")]
    cap_models = _collect_capability_models()

    print("=== repository self-consistency ===")
    ck("1. skill count: state.md == registry.json",
       check_skill_count(state, registry))
    ck("2. latest decision: decisions.md == HANDOFF.md",
       check_decision_number(decisions, handoff))
    ck("3. test suites: PLAYBOOK §V exist & count == state.md",
       check_test_suite_count(playbook, state, lambda p: (ROOT / p).exists()))
    ck("4. manifest keys: runtime.md == validator.MANIFEST_KEYS",
       check_manifest_keys(runtime_md, MANIFEST_KEYS))
    ck("5. no stale/wildcard model refs in capability.json",
       check_no_stale_adapter_wildcards(cap_models, adapter_files))

    print(f"\n{'=' * 58}")
    if FAIL:
        print(f"{len(FAIL)} FAILURE(S): {FAIL}")
        sys.exit(1)
    print("ALL PASS — repository is self-consistent")


if __name__ == "__main__":
    main()

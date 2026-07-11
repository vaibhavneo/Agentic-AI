"""
Unit tests for docs/validate_repo_consistency.py — each check is exercised with
crafted fixtures for BOTH its pass and fail paths, so the suite is deterministic
and independent of the live repo's current state. A final live section asserts
the real repository actually passes (the validator as a gate).

Run: python3 docs/tests/test_repo_consistency.py   (exit 1 on any failure)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs"))

import validate_repo_consistency as v   # noqa: E402

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def _passed(result):
    return result[0] is True


def _failed(result):
    return result[0] is False


# ── Check 1 ──────────────────────────────────────────────────────────────────
def test_skill_count():
    print("=== 1. skill count ===")
    reg = {"skills": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
    state_ok = "| skill_library | COMPLETE: 3 skills (incl. echo) | ... |"
    check("match passes", _passed(v.check_skill_count(state_ok, reg)))
    state_bad = "| skill_library | COMPLETE: 11 skills (incl. echo) | ... |"
    check("mismatch fails", _failed(v.check_skill_count(state_bad, reg)))
    check("reads skill_library row not a stray number",
          _passed(v.check_skill_count("foo 99 skills bar\nskill_library: 3 skills", reg)))
    check("missing claim fails", _failed(v.check_skill_count("no claim here", reg)))


# ── Check 2 ──────────────────────────────────────────────────────────────────
def test_decision_number():
    print("=== 2. latest decision number ===")
    decisions = "- **D1 — x**\n- **D2 — y**\n- **D18 — z**\n"
    check("D18 == D18 passes",
          _passed(v.check_decision_number(decisions, "ADRs D1-D18 here")))
    check("range D1-D18 picks max",
          _passed(v.check_decision_number(decisions, "ADRs D1–D18 (append-only)")))
    check("stale handoff fails",
          _failed(v.check_decision_number(decisions, "ADRs D1–D12 (append-only)")))
    check("no handoff ref fails",
          _failed(v.check_decision_number(decisions, "nothing here")))


# ── Check 3 ──────────────────────────────────────────────────────────────────
PLAYBOOK_FIX = """## §V Validation Checklist

```
python3 a/test_one.py        # comment
python3 b/test_two.py
python3 a/test_one.py        # duplicate, dedup
```
## Next Section
python3 c/test_three.py
"""


def test_test_suite_count():
    print("=== 3. documented test suites ===")
    suites = v.parse_documented_suites(PLAYBOOK_FIX)
    check("parses §V block only (2 unique, ignores next section)",
          suites == ["a/test_one.py", "b/test_two.py"], suites)
    state = "status: 2/2 test suites green"
    check("all exist + count match passes",
          _passed(v.check_test_suite_count(PLAYBOOK_FIX, state, lambda p: True)))
    check("missing suite fails",
          _failed(v.check_test_suite_count(
              PLAYBOOK_FIX, state, lambda p: p != "b/test_two.py")))
    check("count mismatch fails",
          _failed(v.check_test_suite_count(
              PLAYBOOK_FIX, "status: 7/7 test suites green", lambda p: True)))


# ── Check 4 ──────────────────────────────────────────────────────────────────
def test_manifest_keys():
    print("=== 4. manifest required keys ===")
    rt = ("2. **LOAD_MANIFEST** — all 12 manifest keys present "
          "(id, name, version, description, purpose, inputs, outputs, memory, "
          "execution, dependencies, evaluation, tags)")
    keys = {"id", "name", "version", "description", "purpose", "inputs",
            "outputs", "memory", "execution", "dependencies", "evaluation", "tags"}
    check("exact set passes", _passed(v.check_manifest_keys(rt, keys)))
    check("extra code key fails", _failed(v.check_manifest_keys(rt, keys | {"extra"})))
    check("missing code key fails", _failed(v.check_manifest_keys(rt, keys - {"tags"})))
    check("unparseable runtime.md fails",
          _failed(v.check_manifest_keys("no list here", keys)))


# ── Check 5 ──────────────────────────────────────────────────────────────────
ADAPTERS = ["Claude_Opus.md", "Claude_Sonnet.md", "GPT.md", "Gemini.md", "README.md"]


def test_stale_adapter_wildcards():
    print("=== 5. stale/wildcard model refs ===")
    good = [("a/capability.json", m) for m in
            ["claude-opus", "claude-sonnet", "gpt-5", "gemini"]]
    check("all real refs resolve",
          _passed(v.check_no_stale_adapter_wildcards(good, ADAPTERS)))
    check("wildcard star flagged",
          _failed(v.check_no_stale_adapter_wildcards(
              [("s", "claude-*")], ADAPTERS)))
    check("-latest alias flagged",
          _failed(v.check_no_stale_adapter_wildcards(
              [("s", "claude-3-7-sonnet-latest")], ADAPTERS)))
    check("unfilled placeholder flagged",
          _failed(v.check_no_stale_adapter_wildcards(
              [("s", "__model-a__")], ADAPTERS)))
    check("foreign vendor is stale",
          _failed(v.check_no_stale_adapter_wildcards(
              [("s", "mistral-large")], ADAPTERS)))
    check("classify_model_ref: readme excluded from tokens",
          v.classify_model_ref("readme", v.adapter_tokens(ADAPTERS)) == "stale")


# ── Live gate ────────────────────────────────────────────────────────────────
def test_live_repository_is_consistent():
    print("=== live repository self-consistency ===")
    import json
    state = (ROOT / "memory/state.md").read_text()
    registry = json.loads((ROOT / "brain/skills/registry.json").read_text())
    decisions = (ROOT / "memory/decisions.md").read_text()
    handoff = (ROOT / "HANDOFF.md").read_text()
    playbook = (ROOT / "IMPLEMENTATION_PLAYBOOK.md").read_text()
    runtime_md = (ROOT / "brain/runtime/runtime.md").read_text()
    from aios_core.skill_sdk.validator import MANIFEST_KEYS
    adapter_files = [p.name for p in (ROOT / "model_adapters").glob("*.md")]
    cap_models = v._collect_capability_models()

    check("live 1 skill count", _passed(v.check_skill_count(state, registry)))
    check("live 2 decision number",
          _passed(v.check_decision_number(decisions, handoff)))
    check("live 3 test suites",
          _passed(v.check_test_suite_count(
              playbook, state, lambda p: (ROOT / p).exists())))
    check("live 4 manifest keys",
          _passed(v.check_manifest_keys(runtime_md, MANIFEST_KEYS)))
    check("live 5 no stale wildcards",
          _passed(v.check_no_stale_adapter_wildcards(cap_models, adapter_files)))


if __name__ == "__main__":
    test_skill_count()
    test_decision_number()
    test_test_suite_count()
    test_manifest_keys()
    test_stale_adapter_wildcards()
    test_live_repository_is_consistent()
    print(f"\n{'=' * 58}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — validator logic verified + live repo consistent")

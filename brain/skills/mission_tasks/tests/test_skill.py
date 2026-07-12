"""
Tests for mission_tasks — replay every example against its own fixture,
assert every evaluation MUST (E1-E5), plus WP-3's own required validations:
invalid transitions, duplicate submissions, concurrent updates to different
tasks, and cache/index-adjacent memory-permission enforcement.

Deterministic, no model, no network. Idempotent: every test builds its own
temp memory_root and never touches real mission data.

Run: python3 brain/skills/mission_tasks/tests/test_skill.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ROOT = SKILL_DIR.parents[2]                     # brain/skills/mission_tasks -> repo root
sys.path.insert(0, str(ROOT))

from aios_core import skill                      # noqa: E402

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def _fixture(text: str) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "plan.md").write_text(text)
    return d


def _run(root: Path, **inputs):
    return skill.run("mission_tasks", {"memory_root": str(root), **inputs})


FIXTURE_PLAN = "# plan.md\n## Objective\nx\n## Tasks\n- [ ] Read chapter 1\n- [x] Set up the repo\n"


def test_examples_replay():
    print("=== replay examples/*.json against their own fixtures ===")
    for ex_file in sorted((SKILL_DIR / "examples").glob("*.json")):
        ex = json.loads(ex_file.read_text())
        root = _fixture(ex["fixture_plan_md"])
        r = _run(root, **ex["inputs"])
        if ex.get("expected_failure"):
            check(f"{ex_file.name}: {ex['expected_failure']}",
                  r.failure == ex["expected_failure"], str(r.failure))
            continue
        check(f"{ex_file.name}: ok", r.ok, r.failure_detail)
        if r.ok:
            exp = ex["expected_output"]
            check(f"{ex_file.name}: changed=={exp['changed']}",
                  r.output["changed"] == exp["changed"])
            check(f"{ex_file.name}: task matches",
                  r.output["task"] == exp["task"], str(r.output["task"]))


def test_e1_create_idempotent_by_content():
    print("=== E1: create is idempotent by content ===")
    root = _fixture(FIXTURE_PLAN)
    r1 = _run(root, op="create", description="Write the API tests")
    check("first create ok + changed", r1.ok and r1.output["changed"] is True)
    lines_after_1 = (root / "plan.md").read_text().splitlines()

    r2 = _run(root, op="create", description="Write the API tests")
    check("duplicate create ok but changed=False", r2.ok and r2.output["changed"] is False)
    check("duplicate create returns the SAME task id",
          r2.output["task"]["id"] == r1.output["task"]["id"], str((r1.output, r2.output)))
    lines_after_2 = (root / "plan.md").read_text().splitlines()
    check("no duplicate line was appended (file unchanged by the 2nd call)",
          lines_after_1 == lines_after_2)
    check("exactly one new task line exists",
          sum(1 for ln in lines_after_2 if "Write the API tests" in ln) == 1)


def test_e2_set_done_idempotent_by_state():
    print("=== E2: set_done is idempotent by state ===")
    root = _fixture(FIXTURE_PLAN)
    before = (root / "plan.md").read_text()

    r_noop = _run(root, op="set_done", task_id=5, done=True)  # 'Set up the repo' — already done
    check("setting the CURRENT state is a no-op", r_noop.ok and r_noop.output["changed"] is False,
          r_noop.failure_detail)
    check("file bytes unchanged by the no-op", (root / "plan.md").read_text() == before)

    r_flip = _run(root, op="set_done", task_id=4, done=True)  # 'Read chapter 1' — currently not done
    check("flipping to a NEW state writes", r_flip.ok and r_flip.output["changed"] is True,
          r_flip.failure_detail)
    check("exactly one character changed (only that line's checkbox)",
          (root / "plan.md").read_text().splitlines()[4] == "- [x] Read chapter 1")


def test_e3_invalid_transitions():
    print("=== E3: invalid transitions are typed failures ===")
    root = _fixture(FIXTURE_PLAN)
    r_oob = _run(root, op="set_done", task_id=99, done=True)
    check("out-of-range task_id -> EXECUTION_ERROR", r_oob.failure == "EXECUTION_ERROR")
    r_not_task = _run(root, op="set_done", task_id=1, done=True)   # '## Objective' line
    check("non-task line -> EXECUTION_ERROR", r_not_task.failure == "EXECUTION_ERROR")
    # Schema-level rejection (minLength:1) catches an EXPLICIT blank string —
    # that's INPUT_INVALID, a step earlier than the driver ever runs.
    r_blank = _run(root, op="create", description="")
    check("explicit blank description -> INPUT_INVALID (schema minLength)",
          r_blank.failure == "INPUT_INVALID", str(r_blank.failure))
    # An OMITTED description can't be caught by the schema (only conditionally
    # required per op) — that's the driver's own conditional-requiredness check.
    r_missing = skill.run("mission_tasks", {"memory_root": str(root), "op": "create"})
    check("omitted description -> EXECUTION_ERROR (driver's conditional check)",
          r_missing.failure == "EXECUTION_ERROR", str(r_missing.failure))
    r_bad_op = skill.run("mission_tasks", {"memory_root": str(root), "op": "delete"})
    check("unknown op -> INPUT_INVALID (schema enum)", r_bad_op.failure == "INPUT_INVALID")
    check("file untouched by any of the above",
          (root / "plan.md").read_text() == FIXTURE_PLAN)


def test_duplicate_submissions():
    print("=== duplicate submissions (double-click / retry) never double-write ===")
    root = _fixture(FIXTURE_PLAN)
    results = [_run(root, op="create", description="Ship the release") for _ in range(3)]
    check("all three calls ok", all(r.ok for r in results))
    check("only the first call changed the file",
          [r.output["changed"] for r in results] == [True, False, False])
    check("all three return the same task id",
          len({r.output["task"]["id"] for r in results}) == 1)
    check("exactly one line for the task in the final file",
          sum(1 for ln in (root / "plan.md").read_text().splitlines()
              if "Ship the release" in ln) == 1)


def test_concurrent_updates_to_different_tasks():
    print("=== concurrent set_done on DIFFERENT tasks both land ===")
    root = _fixture(FIXTURE_PLAN)
    # fixture already has 2 tasks (ids 4,5); add 2 more so we have fresh,
    # not-yet-done targets for the concurrency check (ids 6,7)
    r_a = _run(root, op="create", description="Task A")
    r_b = _run(root, op="create", description="Task B")
    ids = [r_a.output["task"]["id"], r_b.output["task"]["id"]]
    check("new tasks landed at the expected fresh ids", ids == [6, 7], str(ids))

    results = {}
    def worker(tid):
        results[tid] = _run(root, op="set_done", task_id=tid, done=True)
    threads = [threading.Thread(target=worker, args=(t,)) for t in ids]
    for t in threads: t.start()
    for t in threads: t.join()

    check("both concurrent dispatches ok", all(r.ok for r in results.values()))
    final = (root / "plan.md").read_text().splitlines()
    check("both target tasks ended up checked",
          all(final[tid].startswith("- [x]") for tid in ids), str(final))
    check("the pre-existing, untouched task is still unchecked (control)",
          final[4] == "- [ ] Read chapter 1")


def test_e4_memory_violation_enforced_not_assumed():
    print("=== E4: dispatcher rejects a write outside the allowlist (not self-policed) ===")
    from aios_core.runtime.registry import Registry
    from aios_core.runtime.dispatcher import dispatch

    root = _fixture(FIXTURE_PLAN)
    reg = Registry()
    manifest = dict(reg.get_manifest("mission_tasks"))
    # Simulate a regressed driver that ALSO writes state.md — prove the
    # dispatcher's own snapshot-diff catches it; this is not asserted from
    # inside the driver, so it tests the enforcement layer, per E4's spec.
    bad_manifest_dir = ROOT / "brain" / "skills" / "mission_tasks"

    class _BadDriverModule:
        @staticmethod
        def run(inputs, context):
            (Path(inputs["memory_root"]) / "state.md").write_text("should never happen")
            return {"op": "create", "task": {"id": 0, "description": "x", "done": False},
                    "changed": True}

    import types
    fake_mod_name = "aios_core.runtime.drivers._mission_tasks_bad_test_driver"
    sys.modules[fake_mod_name] = types.SimpleNamespace(run=_BadDriverModule.run)
    manifest["execution"] = dict(manifest["execution"])
    manifest["execution"]["runtime"] = {"type": "python",
                                        "entrypoint": f"{fake_mod_name}:run"}

    class _FixedRegistry(Registry):
        def get_manifest(self, skill_id, version_constraint="*"):
            if skill_id == "mission_tasks":
                return manifest
            return super().get_manifest(skill_id, version_constraint)

        def resolve_dependencies(self, skill_id, include_optional=False):
            return None

    r = dispatch("mission_tasks", {"memory_root": str(root), "op": "create",
                                   "description": "y"}, registry=_FixedRegistry())
    check("write outside the allowlist -> MEMORY_VIOLATION (dispatcher-caught)",
          r.failure == "MEMORY_VIOLATION", str(r.failure))
    del sys.modules[fake_mod_name]


def test_e5_output_schema_and_changed_matches_bytes():
    print("=== E5: output schema conformance; 'changed' matches the real diff ===")
    root = _fixture(FIXTURE_PLAN)
    before = (root / "plan.md").read_text()
    r = _run(root, op="set_done", task_id=4, done=True)
    check("dispatch ok (schema-validated by the runtime)", r.ok, r.failure_detail)
    for key in ("op", "task", "changed"):
        check(f"output has '{key}'", key in r.output)
    after = (root / "plan.md").read_text()
    check("changed=True matches an ACTUAL byte diff", r.output["changed"] == (before != after))

    r2 = _run(root, op="set_done", task_id=4, done=True)   # already done now
    before2 = after
    after2 = (root / "plan.md").read_text()
    check("changed=False matches NO byte diff", r2.output["changed"] == (before2 != after2)
          and r2.output["changed"] is False)


def test_cache_index_rebuildability():
    print("=== plan.md remains the source of truth; mission.get() derives from it ===")
    from aios_core import mission as _mission
    with tempfile.TemporaryDirectory() as td:
        store = _mission.MissionStore(missions_dir=Path(td), db_path=Path(td) / "aios.db")
        m = store.create("Rebuild Check", "build", "verify tasks derive from plan.md",
                         corpora=["curated-wiki"], tasks=["seed task"])
        slug = m["id"]
        root = store.missions_dir / slug
        r = _run(root, op="create", description="added via skill")
        check("create via skill ok", r.ok, r.failure_detail)

        # Read tasks purely from mission.get() (files) — no cache/db involved.
        got = store.get(slug)
        names = [t["description"] for t in got["tasks"]]
        check("new task visible via mission.get() (file is the ONLY source read)",
              "added via skill" in names, str(names))

        # Drop the SQLite mirror entirely and rebuild the view from files alone.
        (store.db_path).unlink(missing_ok=True)
        got2 = store.get(slug)
        check("mission.get() still works with the db file deleted (index is rebuildable, P2)",
              got2["tasks"] == got["tasks"])


if __name__ == "__main__":
    test_examples_replay()
    test_e1_create_idempotent_by_content()
    test_e2_set_done_idempotent_by_state()
    test_e3_invalid_transitions()
    test_duplicate_submissions()
    test_concurrent_updates_to_different_tasks()
    test_e4_memory_violation_enforced_not_assumed()
    test_e5_output_schema_and_changed_matches_bytes()
    test_cache_index_rebuildability()
    print("=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — mission_tasks: idempotent, permission-enforced, file-sourced")

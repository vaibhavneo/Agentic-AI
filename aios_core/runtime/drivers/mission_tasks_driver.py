"""
Reference driver for the mission_tasks skill (v1.0.0).

Implements execution_contract.md deterministically: create or set_done over
plan.md's task lines (the SAME `- [ ] `/`- [x] ` syntax and line-index id
space `aios_core.sdk.mission.MissionStore._parse_tasks` already reads).
Idempotent by construction — create dedupes by exact description text,
set_done no-ops when the target state already holds — so a retried/duplicate
call is always safe. No model or vendor is named in this file (P8); this
skill has no adapter seam at all (fully mechanical).
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

_TASK_RE = re.compile(r"^- \[( |x)\] (.+)$")

# Serializes the read-modify-write below per plan.md path, WITHIN this
# process. Concurrent dispatches against the SAME mission (e.g. two browser
# tabs, or a double-click racing a retry) would otherwise both read the file
# before either writes, and the second write silently discards the first —
# a lost update, not merely an ordering ambiguity, and it reproduces even for
# two DIFFERENT task ids. This does not cover multiple server PROCESSES
# writing the same file (out of scope — same single-user assumption already
# accepted for plan.md elsewhere, IMPLEMENTATION_PLAYBOOK.md M-P1c Risks).
_locks_guard = threading.Lock()
_path_locks: dict[str, threading.Lock] = {}


def _lock_for(path: Path) -> threading.Lock:
    # Path.resolve() normalizes without requiring the file to exist (Python
    # 3.6+, non-strict) — the key must be stable whether or not plan.md has
    # been created yet, so every dispatch against the same mission maps to
    # the exact same Lock object.
    key = str(path.resolve())
    with _locks_guard:
        return _path_locks.setdefault(key, threading.Lock())


def _read_lines(plan: Path) -> list[str]:
    return plan.read_text().splitlines() if plan.exists() else []


def _write_lines(plan: Path, lines: list[str]) -> None:
    plan.write_text("\n".join(lines) + "\n")


def _create(plan: Path, lines: list[str], description: str) -> dict:
    if not description or not description.strip():
        raise ValueError("description required for op=create")
    description = description.strip()
    for i, line in enumerate(lines):
        m = _TASK_RE.match(line)
        if m and m.group(2) == description:
            return {"op": "create",
                    "task": {"id": i, "description": description,
                             "done": m.group(1) == "x"},
                    "changed": False}
    new_id = len(lines)
    lines.append(f"- [ ] {description}")
    _write_lines(plan, lines)
    return {"op": "create", "task": {"id": new_id, "description": description,
                                     "done": False}, "changed": True}


def _set_done(plan: Path, lines: list[str], task_id, done) -> dict:
    if task_id is None:
        raise ValueError("task_id required for op=set_done")
    if done is None:
        raise ValueError("done required for op=set_done")
    if not isinstance(task_id, int) or task_id < 0 or task_id >= len(lines):
        raise ValueError(f"unknown task_id: {task_id}")
    m = _TASK_RE.match(lines[task_id])
    if not m:
        raise ValueError(f"unknown task_id: {task_id} (not a task line)")
    description = m.group(2)
    current_done = m.group(1) == "x"
    if current_done == bool(done):
        return {"op": "set_done",
                "task": {"id": task_id, "description": description,
                         "done": current_done}, "changed": False}
    lines[task_id] = f"- [{'x' if done else ' '}] {description}"
    _write_lines(plan, lines)
    return {"op": "set_done", "task": {"id": task_id, "description": description,
                                       "done": bool(done)}, "changed": True}


def run(inputs: dict, context: dict) -> dict:
    root = Path(inputs["memory_root"]).expanduser()
    plan = root / "plan.md"
    op = inputs["op"]

    with _lock_for(plan):                   # serialize the whole read-modify-write
        lines = _read_lines(plan)
        if op == "create":
            return _create(plan, lines, inputs.get("description"))
        if op == "set_done":
            return _set_done(plan, lines, inputs.get("task_id"), inputs.get("done"))
        raise ValueError(f"unknown op: {op}")      # unreachable — schema enum-enforced

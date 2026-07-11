"""
Reference driver for the recursive_planner skill (v1.0.0).

Implements the mechanical parts of execution_contract.md deterministically:
memory bootstrap (cycle 0), criteria evaluation, convergence tracking, and
memory updates. The REASONING part — choosing and performing the atomic task —
is delegated to context["task_executor"] (any model or function can supply it),
keeping the runtime model-agnostic. Default task_executor is a bootstrap no-op.

One call = ONE cycle. Loop by calling repeatedly (see dispatcher.run_loop).
"""
from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

_STATE_TEMPLATE = """# state.md — Current System State
## Meta
- goal: {goal}
- loop_iteration: {cycle}
- status: {status}
- criteria_streak: {streak}
- last_updated: {today}
## Stability Criteria
{criteria}
"""


def run(inputs: dict, context: dict) -> dict:
    root = Path(inputs["memory_root"]).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    state_f, plan_f = root / "state.md", root / "plan.md"
    log_f, dec_f = root / "log.md", root / "decisions.md"

    # ── Step 1: LOAD MEMORY (bootstrap if cycle 0) ─────────────────────────
    bootstrap = not state_f.exists()
    cycle = 1 if bootstrap else _read_int(state_f, "loop_iteration") + 1
    streak = 0 if bootstrap else _read_int(state_f, "criteria_streak")

    if bootstrap:
        plan_f.write_text("# plan.md\n## Objective\n" + inputs["goal"] +
                          "\n## Next Action\n- [ ] 1.1 first atomic task\n")
        log_f.write_text("# log.md\n")
        dec_f.write_text("# decisions.md\n")

    # ── Steps 2-5: RETRIEVE / SELECT / EXECUTE / VALIDATE — delegated ─────
    task_executor = context.get("task_executor", _bootstrap_task)
    task_result = task_executor(inputs, root, cycle)
    atomic_task = task_result.get("atomic_task",
                                  {"id": "0.0", "description": "bootstrap"})
    artifacts = task_result.get("artifacts", [])
    validation = task_result.get("validation", [])

    # ── Step 8 precompute: criteria evaluation (deterministic) ────────────
    criteria_state = {}
    for c in inputs["stability_criteria"]:
        try:
            r = subprocess.run(c["check"], shell=True, capture_output=True,
                               timeout=60, cwd=str(root))
            criteria_state[c["id"]] = (r.returncode == 0)
        except Exception:
            criteria_state[c["id"]] = False
    all_pass = all(criteria_state.values())
    streak = streak + 1 if all_pass else 0

    if all_pass and streak >= 2:
        status = "STABLE"
    elif cycle >= inputs.get("max_cycles", 25):
        status = "ABORTED"
    else:
        status = "CONTINUE"

    # ── Steps 6-7: COMPRESS + UPDATE STATE (order per contract) ───────────
    with open(log_f, "a") as f:
        f.write(f"- {date.today().isoformat()} C{cycle} "
                f"{atomic_task['description'][:80]} → {status}\n")
    crit_lines = "\n".join(
        f"- [{'x' if criteria_state[c['id']] else ' '}] {c['id']}: {c['description']}"
        for c in inputs["stability_criteria"])
    state_f.write_text(_STATE_TEMPLATE.format(
        goal=inputs["goal"], cycle=cycle, status=status, streak=streak,
        today=date.today().isoformat(), criteria=crit_lines))

    return {
        "cycle": cycle,
        "status": status,
        "atomic_task": atomic_task,
        "artifacts": artifacts,
        "memory_updates": ["state.md", "log.md"] + (["plan.md", "decisions.md"] if bootstrap else []),
        "validation": validation,
        "criteria_state": criteria_state,
    }


def _bootstrap_task(inputs, root, cycle):
    return {"atomic_task": {"id": "0.0",
                            "description": "bootstrap memory files" if cycle == 1
                                           else "no-op (no task_executor provided)"},
            "artifacts": [], "validation": []}


def _read_int(f: Path, key: str) -> int:
    m = re.search(rf"{key}:\s*(\d+)", f.read_text())
    return int(m.group(1)) if m else 0

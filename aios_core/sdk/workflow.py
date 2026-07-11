"""
AIOS Core SDK — Workflow API (stable).

Compose skills into chains (outputs → inputs via `$step.field`) and drive cyclic
skills (recursive_planner) to a terminal status. Also provides BackgroundRun —
the ONE canonical async-run helper, so applications stop re-implementing the
"run a loop on a thread and poll status" pattern (requirement #4: eliminate
duplicated runtime logic).

    from aios_core import workflow
    result = workflow.run(workflow_dict)                # sequential chain
    result = workflow.run_loop("recursive_planner", inputs)   # to STABLE
    job = workflow.BackgroundRun(); job.start_loop("recursive_planner", inputs)
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from ..runtime.dispatcher import run_workflow as _run_workflow, run_loop as _run_loop

__all__ = ["run", "run_loop", "load", "run_file", "BackgroundRun"]


def run(workflow: dict, context: dict | None = None, registry=None) -> dict:
    """Execute a workflow dict: steps run sequentially, `$step.field` in a step's
    inputs binds to a prior step's output. Fail-fast, partial results returned."""
    return _run_workflow(workflow, context or {}, registry)


def run_loop(skill_id: str, inputs: dict, context: dict | None = None,
             registry=None, max_dispatches: int = 50) -> dict:
    """Re-dispatch a cyclic skill until STABLE/BLOCKED/ABORTED (or the cap)."""
    return _run_loop(skill_id, inputs, context or {}, registry, max_dispatches)


def load(path) -> dict:
    return json.loads(Path(path).read_text())


def run_file(path, context: dict | None = None, registry=None) -> dict:
    return run(load(path), context, registry)


class BackgroundRun:
    """Canonical background runner for long loops (planner/mission execution).
    Replaces the duplicated thread+status-dict blocks in the console and the
    AIOS API. Thread-safe status snapshot; one run at a time per instance."""

    def __init__(self):
        self._state = {"running": False, "result": None, "label": None}
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._state["running"]

    def start_loop(self, skill_id: str, inputs: dict, context: dict | None = None,
                   label: str | None = None, max_dispatches: int = 50) -> bool:
        """Start a run_loop on a daemon thread. Returns False if one is already
        running (caller should surface HTTP 409)."""
        with self._lock:
            if self._state["running"]:
                return False
            self._state.update(running=True, result=None, label=label)

        def worker():
            try:
                res = run_loop(skill_id, inputs, context, max_dispatches=max_dispatches)
            except Exception as e:  # never leave the flag stuck
                res = {"ok": False, "final_status": f"ERROR: {e}", "cycles": []}
            finally:
                with self._lock:
                    self._state["result"] = res
                    self._state["running"] = False

        threading.Thread(target=worker, daemon=True).start()
        return True

    def status(self) -> dict:
        with self._lock:
            r = self._state["result"]
            return {"running": self._state["running"], "label": self._state["label"],
                    "final_status": r["final_status"] if r else None,
                    "result": r}

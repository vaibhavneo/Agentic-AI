"""
Skill Runtime — Dispatcher (the facade).

dispatch(skill_id, inputs, context) walks the 9-step lifecycle
(lifecycle.LIFECYCLE_STEPS) with typed failures; run_workflow() composes
skills, binding one step's outputs to the next step's inputs; run_loop()
drives cyclic skills (like recursive_planner) until a terminal status.
No model dependency anywhere: reasoning enters only via context adapters.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from .lifecycle import DispatchResult
from .registry import Registry, SKILLS_DIR
from .validator import validate
from . import executor
from . import monitor


def _schema_of(section: dict, manifest_dir: Path) -> dict:
    if "schema_inline" in section:
        return section["schema_inline"]
    return json.loads((manifest_dir / section["schema"]).read_text())


def dispatch(skill_id: str, inputs: dict, context: dict | None = None,
             registry: Registry | None = None,
             version_constraint: str = "*") -> DispatchResult:
    context = context or {}
    reg = registry or Registry()

    def fail(code: str, detail: str, step: str, elapsed: float = 0.0,
             version: str = "") -> DispatchResult:
        monitor.record(skill_id, version, False, elapsed, [], [], failure=code)
        return DispatchResult(ok=False, skill_id=skill_id, version=version,
                              failure=code, failure_detail=detail, failed_step=step)

    # 1-2. DISCOVER + LOAD_MANIFEST (+ dependency resolution & compat)
    try:
        manifest = reg.get_manifest(skill_id, version_constraint)
        reg.resolve_dependencies(skill_id)          # raises on missing/cycle/incompat
    except KeyError as e:
        return fail("SKILL_NOT_FOUND", str(e), "DISCOVER")
    except ValueError as e:
        return fail("DEPENDENCY_UNRESOLVED", str(e), "DISCOVER")
    version = manifest["version"]
    manifest_dir = SKILLS_DIR / skill_id

    # 3. VALIDATE_INPUT (defaults injected in place)
    errs = validate(inputs, _schema_of(manifest["inputs"], manifest_dir))
    if errs:
        return fail("INPUT_INVALID", "; ".join(errs), "VALIDATE_INPUT", version=version)

    # 4. CHECK_MEMORY_PERMS
    mem = manifest["memory"]
    root_param = mem.get("root_param")
    memory_root = None
    if root_param:
        raw = inputs.get(root_param)
        if not raw:
            return fail("MEMORY_ROOT_INVALID",
                        f"input '{root_param}' required by memory contract",
                        "CHECK_MEMORY_PERMS", version=version)
        memory_root = Path(raw).expanduser()

    # 5. EXECUTE (with pre/post memory snapshots for step 7).
    # Retry policy: manifest execution.retries (default 0) retries apply to
    # EXECUTION_ERROR only — NOT_EXECUTABLE and contract failures never retry
    # (they are deterministic; retrying them just repeats the same failure).
    max_attempts = 1 + int(manifest["execution"].get("retries", 0))
    before = monitor.snapshot(memory_root)
    attempts = 0
    with monitor.Timer() as t:
        while True:
            attempts += 1
            try:
                output = executor.execute(manifest, inputs, context)
                break
            except executor.NotExecutable as e:
                return fail("NOT_EXECUTABLE", str(e), "EXECUTE",
                            getattr(t, "elapsed_ms", 0), version)
            except Exception as e:
                if attempts >= max_attempts:
                    monitor.record(skill_id, version, False,
                                   getattr(t, "elapsed_ms", 0), [], [],
                                   failure="EXECUTION_ERROR", attempts=attempts)
                    return DispatchResult(
                        ok=False, skill_id=skill_id, version=version,
                        failure="EXECUTION_ERROR",
                        failure_detail=f"{type(e).__name__}: {e} (after {attempts} attempt(s))",
                        failed_step="EXECUTE")
    after = monitor.snapshot(memory_root)
    changes = monitor.diff(before, after)

    # 6. VALIDATE_OUTPUT
    errs = validate(output, _schema_of(manifest["outputs"], manifest_dir))
    if errs:
        monitor.record(skill_id, version, False, t.elapsed_ms, changes, [],
                       failure="OUTPUT_INVALID")
        return DispatchResult(ok=False, skill_id=skill_id, version=version,
                              output=output, failure="OUTPUT_INVALID",
                              failure_detail="; ".join(errs),
                              failed_step="VALIDATE_OUTPUT", memory_changes=changes)

    # 7. VERIFY_MEMORY — actual changes ⊆ write allowlist
    allowed = mem.get("write", []) + mem.get("append_only", [])
    violations = [p for p in changes
                  if not any(fnmatch.fnmatch(p, pat) for pat in allowed)]

    # 8. RECORD_METRICS (unconditional)
    confidence = output.get("confidence") if isinstance(output, dict) else None
    metrics = monitor.record(skill_id, version, not violations, t.elapsed_ms,
                             changes, output.get("artifacts", []) if isinstance(output, dict) else [],
                             confidence=confidence,
                             failure="MEMORY_VIOLATION" if violations else None,
                             attempts=attempts)

    # 9. RETURN
    if violations:
        return DispatchResult(ok=False, skill_id=skill_id, version=version,
                              output=output, failure="MEMORY_VIOLATION",
                              failure_detail=f"unauthorized writes: {violations}",
                              failed_step="VERIFY_MEMORY", metrics=metrics,
                              memory_changes=changes, violations=violations)
    return DispatchResult(ok=True, skill_id=skill_id, version=version,
                          output=output, metrics=metrics, memory_changes=changes)


# ── Composition ────────────────────────────────────────────────────────────

def _bind(value, step_outputs: dict):
    """Resolve '$stepname.path.to.field' references against prior outputs."""
    if isinstance(value, str) and value.startswith("$"):
        step, *path = value[1:].split(".")
        cur = step_outputs[step]
        for key in path:
            cur = cur[key]
        return cur
    if isinstance(value, dict):
        return {k: _bind(v, step_outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_bind(v, step_outputs) for v in value]
    return value


def run_workflow(workflow: dict, context: dict | None = None,
                 registry: Registry | None = None) -> dict:
    """
    workflow = {"name": ..., "steps": [
        {"step": "plan", "skill": "recursive_planner", "inputs": {...}},
        {"step": "report", "skill": "echo",
         "inputs": {"message": "$plan.status"}}     # ← output→input binding
    ]}
    Stops at first failed step (fail-fast; partial results returned).
    """
    reg = registry or Registry()
    step_outputs: dict[str, dict] = {}
    results = []
    for spec in workflow["steps"]:
        bound_inputs = _bind(spec["inputs"], step_outputs)
        r = dispatch(spec["skill"], bound_inputs, context, reg)
        results.append({"step": spec["step"], **r.to_dict()})
        if not r.ok:
            return {"name": workflow.get("name", ""), "ok": False,
                    "failed_step": spec["step"], "results": results}
        step_outputs[spec["step"]] = r.output or {}
    return {"name": workflow.get("name", ""), "ok": True, "results": results}


def run_loop(skill_id: str, inputs: dict, context: dict | None = None,
             registry: Registry | None = None, max_dispatches: int = 50) -> dict:
    """Drive a cyclic skill until STABLE/BLOCKED/ABORTED (or dispatch cap)."""
    history = []
    for _ in range(max_dispatches):
        r = dispatch(skill_id, inputs, context, registry)
        history.append(r.to_dict())
        if not r.ok:
            return {"ok": False, "final_status": r.failure, "cycles": history}
        if r.output["status"] in ("STABLE", "BLOCKED", "ABORTED"):
            return {"ok": r.output["status"] == "STABLE",
                    "final_status": r.output["status"], "cycles": history}
    return {"ok": False, "final_status": "DISPATCH_CAP", "cycles": history}

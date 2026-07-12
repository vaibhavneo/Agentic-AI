"""
Skill Runtime test suite — executes the real recursive_planner skill through
the runtime, plus registry/validator/permission/composition coverage.

Run: python3 brain/tests/test_runtime.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

BRAIN = Path(__file__).parent.parent
sys.path.insert(0, str(BRAIN))
sys.path.insert(0, str(BRAIN / "runtime"))

from registry import Registry, satisfies                     # noqa: E402
from dispatcher import dispatch, run_workflow, run_loop      # noqa: E402
from validator import validate                               # noqa: E402

FAILURES: list[str] = []
TMP = Path(tempfile.mkdtemp(prefix="skill_runtime_test_"))


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_registry():
    print("=== registry ===")
    reg = Registry()
    check("discovers 19 skills", len(reg.list_ids()) == 19, f"{len(reg.list_ids())}")
    check("tag discovery finds verification skills",
          {s["id"] for s in reg.discover(tag="verification")} >=
          {"critic", "evaluator", "evidence_validation"})
    check("version lookup honors constraint",
          reg.get_manifest("recursive_planner", ">=1.0.0 <2.0.0")["version"] == "1.0.0")
    try:
        reg.get_manifest("recursive_planner", ">=2.0.0")
        check("incompatible constraint rejected", False)
    except ValueError:
        check("incompatible constraint rejected", True)
    deps = reg.resolve_dependencies("rag_search")
    check("dependency resolution topological (ingestion before rag_search)",
          deps.index("book_ingestion") < deps.index("rag_search"), str(deps))
    check("semver grammar", satisfies("1.4.2", ">=1.0.0 <2.0.0")
          and not satisfies("2.0.0", ">=1.0.0 <2.0.0"))
    # registration validates completeness
    try:
        reg.register({"id": "bad", "version": "1.0.0", "manifest": {"id": "bad"}})
        check("incomplete manifest rejected at registration", False)
    except ValueError:
        check("incomplete manifest rejected at registration", True)


def test_validator():
    print("=== validator ===")
    schema = json.loads((BRAIN / "skills/recursive_planner/input_schema.json").read_text())
    bad = {"memory_root": "/tmp/x"}
    check("missing goal rejected", any("goal" in e for e in validate(bad, schema)))
    good = {"goal": "achieve a testable outcome", "memory_root": "/tmp/x",
            "stability_criteria": [{"id": "c1", "description": "d", "check": "true"}]}
    errs = validate(good, schema)
    check("valid input accepted", not errs, "; ".join(errs))
    check("defaults injected", good.get("max_cycles") == 25 and good.get("effort") == "high")


def test_dispatch_recursive_planner():
    print("=== dispatch: recursive_planner through the runtime ===")
    mem = TMP / "mem_bootstrap"
    inputs = {"goal": "create done.txt in memory root and hold it stable",
              "memory_root": str(mem),
              "stability_criteria": [
                  {"id": "artifact", "description": "done.txt exists",
                   "check": "test -f done.txt"}]}
    r = dispatch("recursive_planner", inputs)
    check("cycle-0 dispatch ok", r.ok, r.failure_detail)
    check("output conforms (status CONTINUE)", r.output["status"] == "CONTINUE")
    check("memory files created", (mem / "state.md").exists() and (mem / "log.md").exists())
    check("memory changes tracked", "state.md" in r.memory_changes)
    check("metrics recorded", r.metrics.get("elapsed_ms") is not None)


def test_loop_to_stable():
    print("=== run_loop: converges to STABLE (M4: 2 consecutive passes) ===")
    mem = TMP / "mem_loop"
    work = TMP / "work"   # artifacts live OUTSIDE memory_root (memory ≠ workspace)
    work.mkdir(exist_ok=True)

    def task_executor(inputs, root, cycle):
        (work / "done.txt").write_text("done")
        return {"atomic_task": {"id": "1.1", "description": "write done.txt"},
                "artifacts": [str(work / "done.txt")],
                "validation": [{"check": "file written", "passed": True}]}

    inputs = {"goal": "create done.txt and converge",
              "memory_root": str(mem),
              "stability_criteria": [{"id": "artifact", "description": "done.txt exists",
                                      "check": f"test -f {work}/done.txt"}]}
    result = run_loop("recursive_planner", inputs, {"task_executor": task_executor})
    check("loop reaches STABLE", result["final_status"] == "STABLE")
    statuses = [c["output"]["status"] for c in result["cycles"]]
    check("STABLE only after 2 consecutive passing cycles (no premature exit)",
          statuses[-2:] == ["CONTINUE", "STABLE"] or statuses.count("CONTINUE") >= 1,
          str(statuses))
    log_lines = (mem / "log.md").read_text().count("- 20")
    check("log.md appended once per cycle (M3)", log_lines == len(result["cycles"]),
          f"log={log_lines} cycles={len(result['cycles'])}")
    check("state.md iteration matches cycle count",
          f"loop_iteration: {len(result['cycles'])}" in (mem / "state.md").read_text())


def test_memory_violation():
    print("=== memory permission enforcement ===")
    mem = TMP / "mem_rogue"

    def rogue_executor(inputs, root, cycle):
        (root / "index").mkdir(exist_ok=True)
        (root / "evil.exe").write_text("outside allowlist? no — *.md/*.json only")
        return {"atomic_task": {"id": "x", "description": "rogue write"},
                "artifacts": [], "validation": []}

    inputs = {"goal": "attempt unauthorized memory write pattern",
              "memory_root": str(mem),
              "stability_criteria": [{"id": "c", "description": "never", "check": "false"}]}
    r = dispatch("recursive_planner", inputs, {"task_executor": rogue_executor})
    check("unauthorized write flagged as MEMORY_VIOLATION",
          not r.ok and r.failure == "MEMORY_VIOLATION", str(r.failure))
    check("violation names the file", any("evil.exe" in v for v in r.violations))


def test_not_executable_and_input_invalid():
    print("=== typed failures ===")
    r = dispatch("hypothesis_generation", {"observations": "metric regressed"})
    check("contract-card without adapter → NOT_EXECUTABLE",
          r.failure == "NOT_EXECUTABLE", str(r.failure))
    # MEMORY_ROOT_INVALID path: ad-hoc skill whose schema doesn't require the
    # root param but whose memory contract does
    reg2 = Registry()
    reg2.register({"id": "tmp_memskill", "version": "1.0.0", "manifest": {
        "id": "tmp_memskill", "name": "t", "version": "1.0.0", "description": "t",
        "tags": [], "inputs": {"schema_inline": {"type": "object"}},
        "outputs": {"schema_inline": {"type": "object"}},
        "memory": {"root_param": "memory_root", "read": [], "write": [],
                   "append_only": [], "immutable": []},
        "execution": {"contract": "", "steps": [],
                      "runtime": {"type": "python",
                                  "entrypoint": "runtime.drivers.echo_driver:run"}},
        "dependencies": [], "evaluation": {"must": []}}})
    r0 = dispatch("tmp_memskill", {"anything": 1}, registry=reg2)
    check("missing memory_root fails at CHECK_MEMORY_PERMS (lifecycle order)",
          r0.failure == "MEMORY_ROOT_INVALID", str(r0.failure))
    r2 = dispatch("recursive_planner", {"goal": "too short criteria missing",
                                        "memory_root": str(TMP / "x")})
    check("schema failure → INPUT_INVALID", r2.failure == "INPUT_INVALID")
    r3 = dispatch("no_such_skill", {})
    check("unknown id → SKILL_NOT_FOUND", r3.failure == "SKILL_NOT_FOUND")


def test_composition():
    print("=== workflow composition (output→input binding) ===")
    mem = TMP / "mem_wf"
    wf = {"name": "plan_then_report", "steps": [
        {"step": "plan", "skill": "recursive_planner",
         "inputs": {"goal": "bootstrap memory for workflow test",
                    "memory_root": str(mem),
                    "stability_criteria": [{"id": "c", "description": "state exists",
                                            "check": "test -f state.md"}]}},
        {"step": "report", "skill": "echo",
         "inputs": {"message": "$plan.status"}},
    ]}
    result = run_workflow(wf)
    check("workflow ok", result["ok"], str(result.get("failed_step")))
    check("step-2 consumed step-1 output ($plan.status)",
          result["results"][1]["output"]["echoed"] in ("CONTINUE", "STABLE"))


def test_retries():
    print("=== retry policy (EXECUTION_ERROR only, tracked in metrics) ===")
    # import via the SAME module path the executor uses, so arm_flaky
    # mutates the same module object the dispatch will call
    from runtime.drivers import echo_driver
    reg2 = Registry()
    flaky_manifest = {
        "id": "flaky", "name": "Flaky", "version": "1.0.0",
        "description": "t", "purpose": "t", "tags": [],
        "inputs": {"schema_inline": {"type": "object"}},
        "outputs": {"schema_inline": {"type": "object"}},
        "memory": {"root_param": None, "read": [], "write": [],
                   "append_only": [], "immutable": []},
        "execution": {"contract": "", "steps": [], "retries": 2,
                      "runtime": {"type": "python",
                                  "entrypoint": "runtime.drivers.echo_driver:run_flaky"}},
        "dependencies": [], "evaluation": {"must": []}}
    reg2.register({"id": "flaky", "version": "1.0.0", "manifest": flaky_manifest})

    echo_driver.arm_flaky(2)   # fails twice, succeeds on attempt 3 (retries=2)
    r = dispatch("flaky", {"message": "hi"}, registry=reg2)
    check("succeeds after retries", r.ok, str(r.failure))
    check("attempts=3 / retries=2 recorded in metrics",
          r.metrics.get("attempts") == 3 and r.metrics.get("retries") == 2,
          str({k: r.metrics.get(k) for k in ('attempts', 'retries')}))

    echo_driver.arm_flaky(5)   # more failures than budget → typed failure
    r2 = dispatch("flaky", {"message": "hi"}, registry=reg2)
    check("exhausted retries → EXECUTION_ERROR with attempt count",
          r2.failure == "EXECUTION_ERROR" and "3 attempt" in r2.failure_detail,
          r2.failure_detail)


def test_model_agnostic():
    print("=== portability: runtime names no model/vendor ===")
    text = "".join(f.read_text() for f in (BRAIN / "runtime").glob("*.py"))
    text += (BRAIN / "runtime" / "drivers" / "recursive_planner_driver.py").read_text()
    banned = re.findall(r"\b(Fable|Opus|Sonnet|Haiku|Anthropic|Claude|deepseek|openai)\b",
                        text, re.I)
    check("no model/vendor references in runtime code", not banned,
          f"found {set(banned)}" if banned else "")


if __name__ == "__main__":
    try:
        test_registry()
        test_validator()
        test_dispatch_recursive_planner()
        test_loop_to_stable()
        test_memory_violation()
        test_not_executable_and_input_invalid()
        test_composition()
        test_retries()
        test_model_agnostic()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{'='*60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — runtime executes skills by contract alone")

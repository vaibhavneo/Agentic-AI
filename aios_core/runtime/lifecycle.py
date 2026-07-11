"""
Skill Runtime — Lifecycle definition (model-agnostic).

The 9-step lifecycle every dispatch follows. Each step has explicit
preconditions and postconditions; failures are typed and terminal for the
dispatch (no silent fallthrough).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LIFECYCLE_STEPS = [
    "DISCOVER",           # skill id resolves in registry
    "LOAD_MANIFEST",      # manifest parses and is complete
    "VALIDATE_INPUT",     # inputs conform to input schema (defaults injected)
    "CHECK_MEMORY_PERMS", # memory_root resolvable; write allowlist known
    "EXECUTE",            # entrypoint or adapter runs the execution contract
    "VALIDATE_OUTPUT",    # output conforms to output schema
    "VERIFY_MEMORY",      # actual memory changes ⊆ manifest write allowlist
    "RECORD_METRICS",     # metrics appended to the run log
    "RETURN",             # structured result to caller
]

# Typed failure codes — one per step that can fail.
FAILURES = {
    "SKILL_NOT_FOUND":      "DISCOVER",
    "MANIFEST_INVALID":     "LOAD_MANIFEST",
    "INPUT_INVALID":        "VALIDATE_INPUT",
    "MEMORY_ROOT_INVALID":  "CHECK_MEMORY_PERMS",
    "NOT_EXECUTABLE":       "EXECUTE",   # contract-card skill with no adapter provided
    "EXECUTION_ERROR":      "EXECUTE",
    "OUTPUT_INVALID":       "VALIDATE_OUTPUT",
    "MEMORY_VIOLATION":     "VERIFY_MEMORY",
    "DEPENDENCY_UNRESOLVED": "DISCOVER",
}


@dataclass
class DispatchResult:
    ok: bool
    skill_id: str
    version: str = ""
    output: dict | None = None
    failure: str | None = None          # key from FAILURES
    failure_detail: str = ""
    failed_step: str | None = None
    metrics: dict = field(default_factory=dict)
    memory_changes: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "skill_id": self.skill_id, "version": self.version,
            "output": self.output, "failure": self.failure,
            "failure_detail": self.failure_detail, "failed_step": self.failed_step,
            "metrics": self.metrics, "memory_changes": self.memory_changes,
            "violations": self.violations,
        }


# Pre/postconditions, referenced by runtime.md and enforced in dispatcher.py:
# DISCOVER        pre: registry loaded       post: (manifest_ref, version) known
# LOAD_MANIFEST   pre: manifest_ref          post: manifest dict with required keys
# VALIDATE_INPUT  pre: manifest.inputs       post: inputs valid, defaults injected
# CHECK_MEMORY    pre: manifest.memory       post: memory_root exists-or-creatable
# EXECUTE         pre: all above             post: raw output dict OR typed failure
# VALIDATE_OUTPUT pre: raw output            post: output conforms to schema
# VERIFY_MEMORY   pre: pre/post snapshots    post: changes ⊆ write-allowlist
# RECORD_METRICS  always runs (even on failure) — observability is unconditional
# RETURN          post: DispatchResult; no exceptions escape the dispatcher

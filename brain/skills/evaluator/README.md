# Skill: evaluator v1.0.0

**Purpose:** 'Works' is a test result, not a feeling; quality claims without deterministic checks are anecdotes.

**What it does:** Deterministic check runner: shell/test commands to pass-fail report with evidence.

| aspect | value |
|---|---|
| runtime | python → `runtime.drivers.library_drivers:run_evaluator` |
| execution steps | RUN_CHECKS → COLLECT → VERDICT |
| inputs / outputs | schemas in [manifest.json](manifest.json) (`inputs`/`outputs`; canonical machine format — see PROJECT_CHARTER.md §5) |
| memory permissions | stateless (no memory root) |
| dependencies | none |
| failure modes | typed runtime failures (see brain/runtime/lifecycle.py): INPUT_INVALID, NOT_EXECUTABLE, EXECUTION_ERROR (retries=0), OUTPUT_INVALID, MEMORY_VIOLATION |
| success metrics | contract card [skill.md](skill.md); evaluation refs: skill.md [] |
| compatibility | any executor honoring the runtime contracts (Charter P8); registry constraint grammar `>=X.Y.Z <A.B.C` |
| tests | brain/tests/test_library_skills.py (dispatch + failure-path) |

Behavioral contract and design rationale: [skill.md](skill.md).

<!-- GENERATED from manifest.json — regenerate via the script in git history / handoff notes; edit manifest.json + skill.md, not this file. -->

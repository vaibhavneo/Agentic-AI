# Skill: memory_compression v1.0.0

**Purpose:** Unbounded memory files stop being readable in one pass, silently breaking the notebook-first architecture.

**What it does:** M6 compliance audit over a memory root: file size bounds, one-line log entries, separation of concerns.

| aspect | value |
|---|---|
| runtime | python → `runtime.drivers.library_drivers:run_compression_audit` |
| execution steps | SCAN → MEASURE → REPORT |
| inputs / outputs | schemas in [manifest.json](manifest.json) (`inputs`/`outputs`; canonical machine format — see PROJECT_CHARTER.md §5) |
| memory permissions | root=`memory_root` · write: [] · append-only: [] · immutable: ['*'] |
| dependencies | none |
| failure modes | typed runtime failures (see brain/runtime/lifecycle.py): INPUT_INVALID, NOT_EXECUTABLE, EXECUTION_ERROR (retries=0), OUTPUT_INVALID, MEMORY_VIOLATION |
| success metrics | contract card [skill.md](skill.md); evaluation refs: skill.md [] |
| compatibility | any executor honoring the runtime contracts (Charter P8); registry constraint grammar `>=X.Y.Z <A.B.C` |
| tests | brain/tests/test_library_skills.py (dispatch + failure-path) |

Behavioral contract and design rationale: [skill.md](skill.md).

<!-- GENERATED from manifest.json — regenerate via the script in git history / handoff notes; edit manifest.json + skill.md, not this file. -->

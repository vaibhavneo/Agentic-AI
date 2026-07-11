# Skill: book_ingestion v1.1.0

**Purpose:** Raw files are not memory — knowledge is unusable until chunked and indexed for retrieval.

**What it does:** Corpus to chunked retrievable index (paragraph-boundary chunking, JSON index).

| aspect | value |
|---|---|
| runtime | python → `runtime.drivers.library_drivers:run_ingest` |
| execution steps | WALK → READ → CHUNK → WRITE_INDEX |
| inputs / outputs | schemas in [manifest.json](manifest.json) (`inputs`/`outputs`; canonical machine format — see PROJECT_CHARTER.md §5) |
| memory permissions | stateless (no memory root) |
| dependencies | none |
| failure modes | typed runtime failures (see brain/runtime/lifecycle.py): INPUT_INVALID, NOT_EXECUTABLE, EXECUTION_ERROR (retries=0), OUTPUT_INVALID, MEMORY_VIOLATION |
| success metrics | contract card [skill.md](skill.md); evaluation refs: skill.md [] |
| compatibility | any executor honoring the runtime contracts (Charter P8); registry constraint grammar `>=X.Y.Z <A.B.C` |
| tests | brain/tests/test_library_skills.py (dispatch + failure-path) |

Behavioral contract and design rationale: [skill.md](skill.md).

<!-- GENERATED from manifest.json — regenerate via the script in git history / handoff notes; edit manifest.json + skill.md, not this file. -->

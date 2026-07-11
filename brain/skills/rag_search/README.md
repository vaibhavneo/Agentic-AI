# Skill: rag_search v2.0.0

**Purpose:** Answers without receipts are unaccountable; every substantive claim must carry its source or admit absence.

**What it does:** Retrieve-ground-cite answering; extractive fallback without an adapter, generative with one; explicit not-found.

| aspect | value |
|---|---|
| runtime | python → `runtime.drivers.library_drivers:run_rag_search` |
| execution steps | RETRIEVE → GROUND → ANSWER → CITE |
| inputs / outputs | schemas in [manifest.json](manifest.json) (`inputs`/`outputs`; canonical machine format — see PROJECT_CHARTER.md §5) |
| memory permissions | stateless (no memory root) |
| dependencies | book_ingestion >=1.0.0 <3.0.0, retrieve_context >=1.0.0 <3.0.0 |
| failure modes | typed runtime failures (see brain/runtime/lifecycle.py): INPUT_INVALID, NOT_EXECUTABLE, EXECUTION_ERROR (retries=0), OUTPUT_INVALID, MEMORY_VIOLATION |
| success metrics | contract card [skill.md](skill.md); evaluation refs: skill.md [] |
| compatibility | any executor honoring the runtime contracts (Charter P8); registry constraint grammar `>=X.Y.Z <A.B.C` |
| tests | brain/tests/test_library_skills.py (dispatch + failure-path) |

Behavioral contract and design rationale: [skill.md](skill.md).

<!-- GENERATED from manifest.json — regenerate via the script in git history / handoff notes; edit manifest.json + skill.md, not this file. -->

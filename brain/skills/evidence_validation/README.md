# Skill: evidence_validation v1.0.0

**Purpose:** The gate between generated and believed — nothing enters durable memory unverified.

**What it does:** Claim to calibrated confidence + flags (0.5*retrieval_support + 0.5*source_corroboration).

| aspect | value |
|---|---|
| runtime | python → `runtime.drivers.library_drivers:run_validate_claim` |
| execution steps | RETRIEVE_EVIDENCE → SCORE → FLAG |
| inputs / outputs | schemas in [manifest.json](manifest.json) (`inputs`/`outputs`; canonical machine format — see PROJECT_CHARTER.md §5) |
| memory permissions | stateless (no memory root) |
| dependencies | retrieve_context >=1.0.0 <3.0.0 |
| failure modes | typed runtime failures (see brain/runtime/lifecycle.py): INPUT_INVALID, NOT_EXECUTABLE, EXECUTION_ERROR (retries=0), OUTPUT_INVALID, MEMORY_VIOLATION |
| success metrics | contract card [skill.md](skill.md); evaluation refs: skill.md [] |
| compatibility | any executor honoring the runtime contracts (Charter P8); registry constraint grammar `>=X.Y.Z <A.B.C` |
| tests | brain/tests/test_library_skills.py (dispatch + failure-path) |

Behavioral contract and design rationale: [skill.md](skill.md).

<!-- GENERATED from manifest.json — regenerate via the script in git history / handoff notes; edit manifest.json + skill.md, not this file. -->

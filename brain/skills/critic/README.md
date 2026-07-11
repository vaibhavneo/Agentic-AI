# Skill: critic v1.0.0

**Purpose:** Generators grading their own homework reintroduces hallucination; adversarial review breaks the self-confirmation loop.

**What it does:** Adversarial store-wide review: verifies every stored concept against retrieved evidence.

| aspect | value |
|---|---|
| runtime | python → `runtime.drivers.library_drivers:run_critic` |
| execution steps | LOAD_STORE → VERIFY_EACH → REPORT |
| inputs / outputs | schemas in [manifest.json](manifest.json) (`inputs`/`outputs`; canonical machine format — see PROJECT_CHARTER.md §5) |
| memory permissions | stateless (no memory root) |
| dependencies | evidence_validation >=1.0.0 <2.0.0 (optional) |
| failure modes | typed runtime failures (see brain/runtime/lifecycle.py): INPUT_INVALID, NOT_EXECUTABLE, EXECUTION_ERROR (retries=0), OUTPUT_INVALID, MEMORY_VIOLATION |
| success metrics | contract card [skill.md](skill.md); evaluation refs: skill.md [] |
| compatibility | any executor honoring the runtime contracts (Charter P8); registry constraint grammar `>=X.Y.Z <A.B.C` |
| tests | brain/tests/test_library_skills.py (dispatch + failure-path) |

Behavioral contract and design rationale: [skill.md](skill.md).

<!-- GENERATED from manifest.json — regenerate via the script in git history / handoff notes; edit manifest.json + skill.md, not this file. -->

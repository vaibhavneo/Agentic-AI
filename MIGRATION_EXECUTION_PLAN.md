# MIGRATION EXECUTION PLAN — AI Learning Agent → AIOS Core

**Status: implementation handoff. Nothing in this plan has been implemented.**
Prepared 2026-07-09 from repository state alone (D13: repo is sole source of
truth). Prereq reading: PROJECT_CHARTER.md → AIOS_HANDBOOK.md →
IMPLEMENTATION_PLAYBOOK.md → learn_agent/AIOS_ARCHITECTURE.md §7–§8.
Companion prompts: OPUS_MIGRATION_PROMPT.md · SONNET_TASK_TEMPLATES.md.

---

## 1. Scope — what "migrated" means

The **AI Learning Agent** is the legacy tutor inside `learn_agent/`: a
multi-turn RAG chatbot with its own private retrieval stack, predating the
corpus system. **Migrated** means (architecture §3.2 + §7):

1. The tutor is a `teacher` agent-type skill executed through the runtime
   (adapter-gated, schema-validated output) — not a free-floating LLM class.
2. All its retrieval flows through the Retrieval Gateway with corpus scope
   and provenance (P3/P9) — the private pickle index is adopted as a corpus
   or retired.
3. Legacy HTTP routes become thin aliases of skill-backed `/api/*` routes;
   the inline legacy UI is sunset per §7 step 4.
4. Everything the migration writes (concepts, sessions-as-memory) goes
   through dispatcher-enforced memory permissions (D12).

## 2. Boundary audit (2026-07-09)

### Already on AIOS Core — do not touch except where noted
| surface | evidence |
|---|---|
| `learn_agent/aios_api.py` | imports ONLY `aios_core.mission/retrieval`; thin routes |
| `learn_agent/mission_control_service.py` + `mission_control_api.py` | SDK-only, enforced by a source-level test (D16) |
| `static/aios.html`, `static/mission_control.html` | render skill/SDK outputs only (P10) |
| `tests/test_aios_p0.py` (25 checks), `tests/test_mission_control.py` (25 checks) | green in §V |

### Legacy — the migration surface
| component | file(s) | problem |
|---|---|---|
| Tutor LLM | `learn_agent/agent.py` (`LearningAgent`, `get_session`, `_call_llm`) | model called directly; sessions in a process dict (violates P1 spirit); not a skill |
| Private RAG | `learn_agent/knowledge/ingest.py` + `sources.py` + `data/index/knowledge_base.pkl` | second retrieval engine outside the gateway (P9); no corpus provenance, category-scoping instead of corpus-scoping |
| Legacy routes | `server.py` `/ask`, `/learning-path`, `/reset`, `/status` | import `agent.py` directly; bypass runtime entirely |
| Legacy UI | `server.py` inline HTML (~380 lines) served at `/legacy` | logic-bearing string blob inside a server file (P10 smell); sunset decision open (H2) |
| SQLite mirror | `learn_agent/data/aios.db` (written by `aios_core.sdk.mission`) | write-only — no read path (Q1h, decision open) |

## 3. Next milestone — confirmation

**Yes, the documented next milestone is M-P1a (coach triggers)** — stated in
HANDOFF.md ("Next milestone: M-P1a") and memory/plan.md Next Action. Two
caveats the implementer must respect:

- plan.md offers a choice: M-P1a **or** M-Q1 (platform quality). **Both
  await human approval to start** (HANDOFF "Remaining human decisions" #1).
- The Learning-Agent migration proper is **M-P2a** (teacher skill). The
  roadmap (architecture §8) sequences P2 after P1 because M-P2a's DoD
  requires "the coach's mastery metrics see it" — the coach must exist
  first. This plan therefore covers P1 (WP‑1…3) as prerequisite work
  packages, then the migration core (WP‑4…6).

## 4. Affected inventory

- **Files (modify)**: `learn_agent/server.py`, `agent.py`, `aios_api.py`,
  `static/aios.html`, `memory/state.md · plan.md · log.md · decisions.md`,
  `brain/skills/registry.json`, `IMPLEMENTATION_PLAYBOOK.md` §V (if suites added),
  `START_HERE.md` + `AIOS_HANDBOOK.md` (Q1a, WP‑8).
- **Files (new)**: `learn_agent/coach_service.py`; `brain/skills/teacher/`
  (full 11-file profile, D17); `brain/skills/mission_tasks/`;
  possibly `memory/corpora/legacy-tutor-kb/` (H3-dependent).
- **APIs (new)**: `/api/coach` (+accept/dismiss), `POST /api/missions/{slug}/run`,
  mission status poll/SSE, task routes, `/api/teach`.
  **APIs (changed)**: `/ask` → alias of the teach path; `/status` reads corpus
  registry not `get_kb_stats()`. **APIs (removed, last phase)**: `/learning-path`,
  `/reset` (fold into teach modes / session-as-memory).
- **Schemas**: `teacher` + `mission_tasks` manifests (12 required keys incl.
  `purpose`); teacher output schema must include concept fields + exercise
  (M-P2a); `recommendations` persistence (aios.db table **or** mission-file
  form — H4 decides).
- **Tests (extend)**: `learn_agent/tests/test_aios_p0.py`,
  `brain/tests/test_library_skills.py` (teacher/mission_tasks by contract),
  `aios_core/tests/test_skill_sdk.py` untouched but must stay green.
  **Tests (new)**: coach trigger unit tests (synthetic memory fixtures),
  teacher skill package tests, task write-path test that reads plan.md back.

## 5. Remaining human decisions — blocking gates

| # | decision | blocks | source |
|---|---|---|---|
| H1 | Approve M-P1a start (or reorder vs M-Q1) | WP‑1 | HANDOFF #1, plan.md |
| H2 | Keep or retire legacy tutor UI once parity | WP‑6 | HANDOFF #4 |
| H3 | Legacy `knowledge_base.pkl`: adopt via `retrieval.adopt_index()` as a corpus, or retire in favor of the existing `ai-books` corpus (25,812 chunks, likely same source books) | WP‑5 | new — record as decisions.md entry when made |
| H4 | `aios.db` fate: remove write-only mirror or give it a tested read path | WP‑7 | Q1h |
| H5 | `distill.py` DeepSeek path: exercise or retire — the teacher adapter reuses the same key-resolution convention, so decide before WP‑4 wiring | WP‑4 (soft) | HANDOFF #5, Q1i |
| H6 | React migration timing | none (vanilla JS stays, D16) | HANDOFF #3 |

## 6. Work packages

Model assignment follows `model_adapters/`: Opus = whole milestones;
Sonnet = atomic tasks (>4 files → split). Every WP ends with the §V
checklist (12 suites) green — that is part of "done", not optional.

### WP‑0 — Pre-flight baseline *(Sonnet, no approval needed)*
- **Objective**: prove the platform is green before any change.
- **Prerequisites**: none.
- **Files**: none (read-only run).
- **Invariants**: n/a.
- **Tests**: run all 12 §V suites; record counts in the session report.
- **Exit**: 12/12 `ALL PASS`. If not, fixing that becomes the first task (START_HERE step 5).
- **Rollback**: n/a.

### WP‑1 — M-P1a Coach service *(Opus — whole milestone)* — gate: H1
- **Objective**: 7 deterministic trigger scanners over existing memory files
  → ranked, evidence-cited recommendations; accept/dismiss persisted;
  REPLACES Mission Control's 3-rule proto-coach (playbook note).
- **Prerequisites**: WP‑0; H1 approved.
- **Files**: NEW `learn_agent/coach_service.py`; `aios_api.py` (+`/api/coach`,
  accept/dismiss); persistence per H4-pending (default: `recommendations`
  table in aios.db, flagged rebuildable per P2); `static/aios.html` +
  `static/mission_control.html` (coach card replaces proto-coach);
  `mission_control_service.py` (remove proto-coach rules).
- **Invariants**: routes stay thin (P10 — triggers live in coach_service, not
  routes); every recommendation cites file/concept/corpus evidence (P3);
  triggers are deterministic — LLM ranking optional and clearly separated
  (P6); no memory format changes.
- **Tests**: trigger unit tests with synthetic memory fixtures (each trigger:
  ≥1 firing + ≥1 non-firing case); API test; existing 50 UI checks pass.
- **Exit**: fresh boot shows ≥1 evidence-cited suggestion with no prompt;
  accept dispatches; dismissed ids persist across restart; §V green.
- **Rollback**: additive — remove routes/panel/service; restore proto-coach
  block from git-less backup (copy the removed function into the PR notes).

### WP‑2 — M-P1b Execute mode + SSE *(Sonnet, 3 atomic tasks)*
- **Objective**: run missions from the shell; live cycle table; 409 on
  concurrent run. Tasks: (a) run route + thread/queue status (console's
  proven pattern), (b) status/poll or SSE endpoint, (c) Execute tab UI.
- **Prerequisites**: WP‑0 (planner + `workflow.run_loop` already exist; WP‑1
  not required).
- **Files**: `aios_api.py`, `static/aios.html`; nothing outside learn_agent.
- **Invariants**: dispatch only via `aios_core` SDK; no business logic in
  routes; mission memory files remain the only truth (P1/P2).
- **Tests**: extend `test_aios_p0.py`: run-to-STABLE on a seeded mission with
  trivially-true criteria; 409 negative case; cycle rows match metrics.jsonl.
- **Exit**: M-P1b DoD verbatim; §V green.
- **Rollback**: remove tab + routes; mission files unaffected.

### WP‑3 — M-P1c Task write-path + Today's Focus *(Sonnet, 2 atomic tasks)*
- **Objective**: plan.md check/add from UI **through a skill dispatch**;
  Today's Focus card.
- **Prerequisites**: WP‑0. Skill authored per D17 (full profile, validator
  VALID, quality ≥85).
- **Files**: NEW `brain/skills/mission_tasks/` + registry entry;
  `aios_api.py` task routes; `static/aios.html`.
- **Invariants**: manifest write-allowlist = `plan.md` ONLY (dispatcher
  enforces, D12); no direct-file-write path may exist in the API layer;
  registry addition keeps `test_library_skills.py` green.
- **Tests**: dispatch test incl. MEMORY_VIOLATION negative (attempt to write
  state.md via the skill fails); API test verifies plan.md content changed on disk.
- **Exit**: M-P1c DoD verbatim; §V green.
- **Rollback**: remove routes + registry entry; skill dir is inert without registry.

### WP‑4 — M-P2a Teacher skill: the migration core — ✅ DONE 2026-07-10 (H5 resolved, WP‑1 shipped)
- **Objective**: `agent.py`'s tutor becomes `brain/skills/teacher/`
  (agent-type, strict output schema incl. concept fields + exercise);
  `agent.py` is REFRAMED as the adapter — LLM client only, no retrieval, no
  sessions-in-dict (session context comes in via inputs; memory via
  manifest-declared files). Lesson completion → `concept_store.upsert`
  (`{corpus, source}` provenance) → critic verifies.
- **Prerequisites**: WP‑1 (coach reads mastery); WP‑3 pattern (skill-gated
  writes) as reference; H5 decided (key-resolution path).
- **Files**: NEW `brain/skills/teacher/` (11-file full profile) + registry;
  `learn_agent/agent.py` (rewrite as adapter); `aios_api.py` (`/api/teach`);
  `static/aios.html` (Learn tab: socratic/explain/exercise/compare, depth);
  `memory/concepts.json` (grows through the loop, not by hand).
- **Invariants**: runtime never sees a model name (P8 — model lives in the
  adapter); teacher output failing schema is REJECTED, never loosened
  (charter R10 spirit); personal-notes reliability ceiling applies to
  derived concepts; retrieval inside lessons goes through the gateway with
  mission scope (P9) — never `knowledge.ingest.search`.
- **Tests**: `test_library_skills.py` gains teacher contract cases (incl.
  NOT_EXECUTABLE without adapter + schema-reject negative); an API-key-gated
  live test may exist but the suite must pass without keys (stub adapter).
- **Exit**: M-P2a DoD verbatim: a completed lesson measurably changes
  concepts.json (new concept, unverified→critic-scored) and coach mastery
  metrics see it; §V green.
- **Rollback**: keep legacy `/ask` path intact until exit criteria pass
  (§7 "old product keeps working at every step"); revert = remove skill +
  route, restore agent.py from the pre-WP tag/copy.

### WP‑5 — Retrieval unification *(Sonnet, 1–2 atomic tasks)* — gate: H3
- **Objective**: eliminate the second retrieval engine. Either
  `retrieval.adopt_index("legacy-tutor-kb", data/index/knowledge_base.pkl)`
  — only if the pickle can be converted to chunks.json form — or (simpler,
  recommended if book overlap confirms) retire it: `/ask`-era queries scope
  to the `ai-books` corpus.
- **Prerequisites**: WP‑4 (teacher already retrieves via gateway); H3 decided
  + decisions.md entry appended.
- **Files**: `learn_agent/knowledge/` (retire or convert), `server.py`
  `/status` (reads corpus registry), possibly `memory/corpora/registry.json`.
- **Invariants**: no `Retriever` use outside gateway/drivers (charter §7
  testing standards); `test_gateway.py` untouched and green; the flagged
  concept-canary rule (M-K DoD) applies if a new corpus is added.
- **Tests**: grep-style assertion (mirroring `test_runtime.py`'s vendor
  grep): no `knowledge.ingest` imports remain outside `knowledge/` itself;
  gateway test extended if a corpus was adopted.
- **Exit**: exactly one retrieval path exists in learn_agent; §V green.
- **Rollback**: the pickle index is never deleted in this WP — only
  disconnected; reconnecting is one import.

### WP‑6 — Legacy surface sunset *(Sonnet, 2 atomic tasks)* — gate: H2
- **Objective**: §7 step 4. (a) extract the ~380-line inline HTML from
  `server.py` to `static/legacy.html` (mechanical, P10 hygiene); `/ask`
  becomes an alias of the teach path; `/learning-path`, `/reset` fold in or
  410. (b) If H2 says retire: remove `/legacy` after one phase.
- **Prerequisites**: WP‑4 + WP‑5 complete (parity proven).
- **Files**: `server.py` (shrinks substantially), NEW `static/legacy.html`
  (phase 1), `tests/test_aios_p0.py` (route expectations).
- **Invariants**: `/app` and `/` (Mission Control) byte-identical behavior;
  port stays 8003; no logic moves INTO server.py.
- **Tests**: existing UI suites unchanged; alias test: `/ask` and `/api/teach`
  return same-shape payloads.
- **Exit**: server.py contains mounting + thin legacy aliases only; §V green.
- **Rollback**: serve old HTML again (§7 step 5) — keep the extracted file.

### WP‑7 — aios.db resolution *(Sonnet, 1 atomic task)* — gate: H4
- **Objective**: implement whichever H4 chose: delete the mirror writes from
  `aios_core/sdk/mission.py` (+ decisions.md entry) or add a real, tested
  read path (e.g. recommendations store for WP‑1).
- **Prerequisites**: H4; coordinate with WP‑1's persistence choice.
- **Invariants**: files remain source of truth (P2) — DB stays DROP-safe;
  `mission.py` is aios_core — re-run `test_aios_core.py` + `test_aios_p0.py`
  closely (touching the SDK affects every app).
- **Tests**: if removal: suites green with no db file present; if read path:
  a rebuild-from-files test (drop db → regenerate → identical reads).
- **Exit**: Q1h closed either way with a decisions.md entry; §V green.
- **Rollback**: mirror writes are additive code — single revert.

### WP‑8 — Documentation truth pass *(Sonnet, 1 atomic task)*
- **Objective**: Q1a (START_HERE/AIOS_HANDBOOK cover aios_core, packs,
  Mission Control) + update HANDOFF.md "current state in one line"
  (currently says 7/7 suites; state.md says 12/12) + reflect teacher-skill
  reality in AIOS_HANDBOOK §2 ("becomes `teacher` skill in P2" → done).
- **Prerequisites**: ideally last (docs describe the end state), but Q1a's
  critical part may run any time after WP‑0.
- **Invariants**: docs-only; no code. `docs/validate_api_reference.py` still green.
- **Exit**: fresh-engineer audit finds zero missing-subsystem gaps (Q1a DoD).
- **Rollback**: revert doc files.

## 7. Sequencing

```
WP‑0 ──► WP‑1 (H1) ──► WP‑4 (H5) ──► WP‑5 (H3) ──► WP‑6 (H2)
   │                     ▲
   ├──► WP‑2 ────────────┤   (P1b/P1c may run parallel to each other,
   ├──► WP‑3 ────────────┘    both before WP‑4)
   ├──► WP‑7 (H4, coordinate with WP‑1 persistence)
   └──► WP‑8 (Q1a part any time; final truth pass last)
```

Per charter P5 every WP is independently shippable; stop after any green WP
with memory updated (Definition of Done §6) and the system remains coherent.

## 8. Definition of Done (every WP, non-negotiable)

1. Deterministic check written FIRST and passing (P6).
2. All 12 §V suites green (IMPLEMENTATION_PLAYBOOK.md §V).
3. `memory/log.md` +1 line; `state.md` row updated if a component changed;
   `decisions.md` ONLY for H-decisions and irreversible choices.
4. `grep -riE 'fable|opus|sonnet|anthropic' brain/runtime/*.py` still empty (P8).
5. Report evidence (file paths, test output), not adjectives.

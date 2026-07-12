# state.md — Current System State
<!-- What is TRUE right now. No history, no plans. Overwrite in place. -->

## Meta
- project: Second Brain MVP (Fable Loop Engine)
- loop_iteration: 20 (Task write-path M-P1c)
- status: STABLE + VALIDATED + PACKAGED — 16/16 test suites green
- last_updated: 2026-07-11

## Components
| component | state | location |
|---|---|---|
| memory_files | LIVE | memory/ |
| ingest | BUILT+TESTED (4 tests) | second_brain/ingest.py |
| retrieval | BUILT+TESTED (4 tests) | second_brain/retrieve.py |
| distillation | concept_distillation skill (agent-type, adapter-gated, model-agnostic); legacy standalone distill.py RETIRED (D19) | brain/skills/concept_distillation/ |
| concept_store | SOURCE OF TRUTH — 10 concepts, 8 typed edges | memory/concepts.json via second_brain/concept_store.py |
| knowledge_cache.md | RENDERED VIEW ONLY (do not hand-edit) | memory/knowledge_cache.md |
| critic_agent | BUILT+TESTED (5 tests) — deterministic, retrieval-grounded | second_brain/critic.py |
| validation_suite | 20/20 PASS | second_brain/tests/test_pipeline.py → memory/validation_report.md |
| loop_runner | BUILT+PASSING (reads concepts.json) | second_brain/loop.py |
| chunk_index | 36 files / 96 chunks (wiki/books) | memory/index/chunks.json |
| aios_core | v1.0.0 — reusable infra: runtime engine + 6 stable SDK APIs (skill/workflow/agent/memory/retrieval/mission); powers console+AIOS; test_aios_core green (D14) | aios_core/ |
| skill_sdk | v1.1 — template + validator (V1-V10) + quality score + Part-10 benchmark; capability.json (advisory routing/quality, real trace coverage, D18); new skills: full profile ≥85 | aios_core/skill_sdk/, templates/skill/, SKILL_*.md, CAPABILITY_DESCRIPTOR.md |
| domain_packs | v1.0.0 — pluggable knowledge domains via PackManager; zero-core-change (proven); AI-eng pack implemented, PM/finance/astrology specced (D15) | packs/, DOMAIN_PACKS.md |
| skill_library | COMPLETE: 13 skills (incl. echo fixture + teacher M-P2a + mission_tasks M-P1c), all with manifest.json; teacher/mission_tasks = full-profile (VALID, quality 100) | brain/skills/ (AIOS_SKILLS_DIR-configurable) |
| skill_runtime | v1.1.0 — 9-step lifecycle, retries, model-agnostic; MOVED into aios_core/runtime; brain/runtime = compat shims | aios_core/runtime/ |
| workflows | 3 executable (.workflow.json incl. self_check) + 4 documented | brain/workflows/ |
| operator_console | LIVE on :5052 — 8 panels, backend-thin | brain/console/ |
| corpus_manager | 5 corpora (curated-wiki 96, ai-books 25,812, personal-notes 127; finance/llm-books on-demand) | second_brain/corpus_manager.py + memory/corpora/ |
| retrieval_gateway | ONLY retrieval path — scope/normalize/dedup/confidence/provenance; tests green | second_brain/gateway.py |
| aios_p0 | LIVE on :8003/app — mission workspace (2 seeded missions), corpus-scoped search; SDK-only | learn_agent/aios_api.py, static/aios.html |
| mission_control | LIVE on :8003/ (default landing page, D16) — 10-panel dashboard, ⌘K, dockable panels, 15s live poll; SDK-only; 20/20 tests | learn_agent/mission_control_service.py, mission_control_api.py, static/mission_control.html |
| coach | LIVE — M-P1a: 7 deterministic trigger scanners → ranked evidence-cited recs; accept dispatches via runtime, dismiss persists (recommendations table, DROP-safe); proto-coach removed (mission_control delegates here); /api/coach + /app card + '.' key | learn_agent/coach_service.py, aios_api.py, static/aios.html |
| teacher | LIVE — M-P2a/WP-4: adapter-gated teacher skill (stateless; deterministic scope→retrieve→mastery + adapter seam; provenance driver-owned). Integration: teacher_adapter.teach() teach→upsert→critic loop + /api/teach (legacy /ask untouched). Learn-tab UI deferred | brain/skills/teacher/, aios_core/runtime/drivers/teacher_driver.py, learn_agent/teacher_adapter.py, aios_api.py |
| task_write_path | LIVE — M-P1c/WP-3: mission_tasks skill (create/set_done over plan.md task lines; write-allowlist=plan.md ONLY; idempotent by content/state; in-process per-path lock closes a real lost-update race found in testing). POST/PATCH /api/missions/{slug}/tasks + GET /api/today-focus (read-only); interactive Tasks tab + dashboard Today's Focus card | brain/skills/mission_tasks/, aios_core/runtime/drivers/mission_tasks_driver.py, aios_api.py, static/aios.html |
| api_reference | docs/API_REFERENCE.md — real API surface + example payloads, PLANNED items labelled; docs/validate_api_reference.py green (M-Q1 rec #2) | docs/ |
| handoff_docs | COMPLETE — charter/handbook/start-here/playbook/lessons/adapters/workflows; repo is sole source of truth (D13); + migration handoff (plan/Opus prompt/Sonnet templates, C19.1 — planning only) | root *.md, model_adapters/, brain/workflows/WORKFLOWS.md |

## Verification State (from critic, memory/critic_report.md)
- 9/10 concepts supported (confidence 0.73–1.00)
- 1/10 unsupported-by-index: "Grounding Beats Generation" (0.20) — provenance is
  workspace experience; curated book index lacks matching text. Honest flag, kept.
- 3 concepts carry non-index-provenance flags (persistent-memory refs)

## Stability Criteria — ALL PASS
- [x] ingest / retrieval / ≥3 concepts / loop stable across iterations
- [x] NEW: full pipeline validation 20/20

## Known Limits (not blockers)
- Index = curated wiki only (456-book raw/library not ingested) — the main lever
  to raise low-confidence concepts
- Critic is lexical (TF-IDF overlap), not semantic — inherits D2's upgrade path
- START_HERE.md/AIOS_HANDBOOK.md don't yet cover aios_core/packs/Mission
  Control (D14-D16) — see M-Q1a, PLATFORM_IMPROVEMENT_REPORT.md P1 (critical)
- metrics.jsonl unbounded + test-noise pollutes architecture_health() — see
  M-Q1b, PLATFORM_IMPROVEMENT_REPORT.md P2 (critical)

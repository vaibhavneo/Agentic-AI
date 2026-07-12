# IMPLEMENTATION PLAYBOOK — milestones P1+

Prereq reading: PROJECT_CHARTER.md → AIOS_HANDBOOK.md → memory/plan.md.
P0 (corpus manager, gateway, missions, shell, ⌘K) is COMPLETE and verified.
Each milestone below is independently executable and independently shippable.
Design rationale for all of them: `learn_agent/AIOS_ARCHITECTURE.md` §4.4–§8.

---

## M-P1a — Coach service (deterministic triggers) — IMPLEMENTED 2026-07-10 (WP-1)
> Note (2026-07-06): Mission Control (D16) shipped a labeled 3-rule proto-coach — now REMOVED. M-P1a delivered: `learn_agent/coach_service.py` (7 deterministic trigger scanners, ranked, evidence-cited), accept-dispatches-via-runtime + dismiss persistence in an aios.db `recommendations` table (DROP-safe), `/api/coach` (+accept/dismiss), and the `/app` coach card with the `.` accept key. Mission Control now delegates to the coach. Contradiction detector is deferred (fires only on an explicit flag); hot-unread-book consumes an optional `memory/retrieval_stats.json` the gateway does not yet emit (recorded gap).
- **Objective**: the system initiates. 7 trigger scanners over existing files
  produce ranked recommendations with evidence; accept/dismiss recorded.
- **Skills**: retrieve_context, evaluator (no new generative skills needed —
  LLM only for ranking, optional at first).
- **Files**: NEW `learn_agent/coach_service.py`; `aios_api.py` (+`/api/coach`,
  accept/dismiss routes; extend aios.db with `recommendations` table);
  `static/aios.html` (coach card + sidebar badge + `.` accept key).
- **Triggers (from §4.4)**: gap-blocks-task · low-confidence concept ·
  stale mission · hot-unread book (needs per-corpus retrieval_stats — add
  counting in gateway) · retention decay (14d) · contradiction (defer the
  detector; stub the trigger) · mission-ready-to-close.
- **DoD**: `GET /api/coach` returns ≥1 real recommendation against seeded
  missions, each citing its evidence (file/concept/corpus); accept dispatches
  the action; dismissed ids persist. Tests: trigger unit tests with synthetic
  memory fixtures + API test.
- **Exit criteria**: on a fresh morning boot, the dashboard shows ≥1
  evidence-cited suggestion without any user prompt.
- **Risks**: recommendation quality (mitigate: triggers are floors, log
  acceptance rate); noisy triggers (cap at 5, dedupe by action).
- **Rollback**: coach is additive — remove routes/panel; no memory format changes.

## M-P1b — Execute mode + SSE — IMPLEMENTED 2026-07-10 (WP-2)
- **Objective**: run missions from the shell with a live cycle table and
  active-agent indicator.
- **Delivered**: `aios_api.py` gained `POST /missions/{slug}/run`,
  `GET /missions/{slug}/status`, and `GET /missions/{slug}/events` (SSE) — one
  `aios_core.sdk.workflow.BackgroundRun` per mission slug, the SAME canonical
  helper the operator console uses (no second execution/event system). The SSE
  feed is a transport over that single status source: named `cycle` /
  `completed` / `failed` / `idle` events (never the reserved `error`, which
  collides with EventSource's own connection-error signal), each cycle
  carrying an `id:` so a reconnecting client's `Last-Event-ID` skips
  already-delivered cycles (dedup on resume). `aios.html` gained an Execute
  tab: criteria editor, max-cycles input, live cycle table, and an
  `aria-live="polite"` status region cycling idle→loading→running→
  completed/failed, plus a client-only "Stop watching" (`cancelled`) — the
  loop itself has no cancel primitive (see Known limits).
- **Depends**: none (planner + run_loop existed).
- **DoD**: verified — a throwaway mission with `test -f state.md` criteria
  runs to STABLE via the API; cycle rows carry per-criterion ✓/✗; a second
  concurrent run of the SAME mission gets 409; re-run after terminal
  completion succeeds (not falsely 409). Tests:
  `learn_agent/tests/test_aios_p0.py` (`test_execute_*`, `test_shell_execute_mode_markers`).
- **Known limits**: no server-side cancel (a Python thread can't be safely
  killed mid-loop without a cooperative check in `BackgroundRun` itself,
  which is aios_core kernel code — out of this WP's file scope); "cancelled"
  is client-detach only, the background run keeps going to its own terminal
  status. Default `task_executor` never retrieves, so the "ai-books pre-warm"
  risk noted below does not apply to the current no-op bootstrap task.
- **Rollback**: remove tab + 3 routes; mission files unaffected (recursive_planner
  writes only inside its own declared, dispatcher-enforced memory contract).

## M-P1c — Task write-path + Today's Focus
- **Objective**: check/add plan.md tasks from the UI **through a skill
  dispatch** (memory permissions enforced), and a dashboard Today's Focus card
  (first unchecked task of most-recently-active mission).
- **Files**: NEW small `mission_tasks` python skill (driver edits plan.md;
  manifest write allowlist = plan.md only) + registry entry; `aios_api.py`
  task routes; `aios.html`.
- **DoD**: checking a task updates the FILE (verify by reading plan.md),
  progress recomputes, dispatcher logs the memory change; direct-file-write
  path does not exist in the API layer.
- **Risks**: edit collisions (last-write-wins acceptable single-user; note it).

## M-P2a — Learn mode (teach → upsert → critic) — IMPLEMENTED 2026-07-10 (WP-4)
> Delivered: full-profile `teacher` skill (`brain/skills/teacher/`, VALID + quality 100), deterministic driver (`aios_core/runtime/drivers/teacher_driver.py`) that resolves scope → retrieves via the gateway → assesses mastery/prerequisites → delegates the explanation/exercise/mastery-check to `context["agent_adapter"]` → assembles a lesson (explanation · source evidence · exercise · mastery check · next action) with driver-owned provenance. Integration adapter `learn_agent/teacher_adapter.py` (LLM wiring + `teach()` teach→upsert→critic loop) + thin `/api/teach`; legacy `/ask` untouched. Learn-tab UI is the remaining follow-up (structured output is already UI-ready).
- **Objective**: tutor becomes a `teacher` agent-type skill; completing a
  lesson upserts a concept `{corpus, source}` provenance → critic verifies.
- **Files**: NEW `brain/skills/teacher/` (manifest, agent-type, strict output
  schema incl. concept fields + exercise); adapter = `learn_agent/agent.py`
  client; `aios_api.py` `/api/teach`; Learn tab (modes: socratic/explain/
  exercise/compare, depth control).
- **DoD**: a completed lesson measurably changes concepts.json (new concept,
  status unverified→critic-scored) and the coach's mastery metrics see it.
- **Risks**: LLM output drift (schema-validate; reject without kill fields);
  reliability ceiling for personal-notes-derived concepts must apply.

## M-P2b — Retention queue + knowledge graph
- **Objective**: spaced-repetition queue from concept `updated` timestamps;
  interactive graph (nodes: concepts/books/missions/skills; edges from
  concepts.json relationships + provenance + mission_corpora + registry deps).
- **Files**: `graph_service.py` (assemble JSON, cache 60s), `/api/graph`,
  graph view (force-directed; any CDN lib or hand-rolled canvas).
- **DoD**: clicking a graph node shows details + "retrieve about this";
  retention queue surfaces ≥1 due concept when timestamps are aged in a test.

## M-P3 — Depth (architect/code_generator skills, contradiction detector, memory browser)
- As specified in AIOS_ARCHITECTURE.md §8 P3. Gate: only start after P1+P2
  acceptance rates prove the coach loop is used.

## M-K (parallel, any time) — Knowledge expansion
- Ingest remaining corpora: llm-books, finance (PDF profile; expect minutes),
  research-papers, remaining 7 library categories as one corpus each.
- **DoD per corpus**: registry stats populated; gateway test extended with the
  new corpus; the flagged concept "Grounding Beats Generation" is the canary —
  re-run critic after finance ingest and record whether confidence rises (D11).

## M-Q1 — Platform Quality (self-analysis findings, 2026-07-06)
Source: `PLATFORM_IMPROVEMENT_REPORT.md` (full rationale/effort/validation
per item — read it before starting any sub-item below). Queued, not yet
approved to start. Each sub-item is independently executable; do them in
priority order unless a specific one is requested.

- **Q1a (🔴 critical, small)** Refresh `START_HERE.md` + `AIOS_HANDBOOK.md` to
  cover aios_core, Domain Packs, and Mission Control (D14–D16 currently
  undocumented in the onboarding path). DoD: re-run a fresh-engineer-style
  audit and confirm zero missing-subsystem gaps.
- **Q1b (🔴 critical, medium)** `metrics.jsonl` retention + correctness: add
  rotation/bound (mirrors the `.md` 200-line precedent) and stop test-fixture
  dispatches (`echo`, `flaky`, `no_such_skill`, `tmp_memskill`, `pack_probe`)
  from polluting `architecture_health()`'s success-rate signal. DoD: a
  repeated full-suite run does not change the reported success rate; file
  stays bounded under continuous use.
- **Q1c (🟠 high, small)** Remove the `echo` test fixture from the production
  `brain/skills/registry.json`; move it to a test-only registry. DoD:
  `len(Registry().list_ids()) == 10` (currently `>= 10`, itself a smell).
- **Q1d (🟡 medium, small)** Standardize on `mission` (not `mission_id`) end
  to end — gateway, SDK, routes. DoD: grep for `mission_id` inside
  `aios_core/` and `second_brain/gateway.py` returns nothing.
- **Q1e (🟡 medium, small)** Extract the duplicated command-palette JS
  (`aios.html` + `mission_control.html`) into one shared
  `learn_agent/static/aios-shared.js`, no build step. DoD: existing shell
  tests pass unchanged; both HTML files reference the same script.
- **Q1f (🟡 medium, decision-only)** Record a `decisions.md` entry explaining
  the Flask (console) / FastAPI (learn_agent) split so it reads as
  intentional. No code change.
- **Q1g (🟢 low, trivial)** Fix `runtime.md`'s manifest key list to include
  `purpose` (12 keys, not 11) — a repeat finding from a prior audit, never
  landed; bundle into whichever session next touches `runtime.md`.
- **Q1h (🟢 low, small)** Decide `aios.db`'s fate: remove the write-only
  SQLite mission mirror (YAGNI, per D4) or give it a real, tested read path.
- **Q1i (🟢 low, small–medium)** Resolve `distill.py`'s 14-cycle-old
  untested LLM path: fix with a real (API-key-gated) test, or formally
  retire it via a `decisions.md` entry and remove the "known limit" line
  from `state.md`.
- **Q1j (🟢 low, trivial)** Replace the unmeasured "ai-books ≈ seconds"
  latency claim in `LESSONS.md` §3 with an actual timed measurement.

- **DoD (whole milestone)**: all sub-items either done or explicitly
  deferred with a decisions.md entry; §V Validation Checklist still green;
  `PLATFORM_IMPROVEMENT_REPORT.md`'s findings table updated to show
  resolved/deferred status per row.
- **Risks**: Q1b touches the runtime's monitor module — re-run
  `test_runtime.py` and `test_aios_core.py` closely since retry/metrics
  logic is contract-tested there. Q1c/Q1d are mechanical but touch files
  every existing suite exercises — expect to re-run the full §V checklist,
  not just the changed area's own tests.
- **Rollback**: every sub-item is additive-or-mechanical (doc edits, a
  rename, an extraction, a registry split) — revert the specific file(s)
  changed; no sub-item alters memory file formats or the runtime contract.

---

## §V Validation Checklist (after EVERY milestone)

```
python3 second_brain/tests/test_pipeline.py        # knowledge pipeline (20)
python3 second_brain/tests/test_gateway.py         # scope/provenance/honesty
python3 aios_core/tests/test_aios_core.py          # SDK + shims + multi-app (D14)
python3 aios_core/tests/test_skill_sdk.py          # skill validator/quality/benchmark (D17)
python3 aios_core/tests/test_capability.py         # capability descriptors (D18)
python3 brain/tests/test_runtime.py                # lifecycle/permissions/retries
python3 brain/tests/test_library_skills.py         # every skill by contract
python3 brain/tests/test_console.py                # operator console
python3 learn_agent/tests/test_aios_p0.py          # AIOS acceptance
python3 brain/skills/recursive_planner/tests/test_skill_package.py
python3 packs/tests/test_domain_packs.py          # domain packs (D15)
python3 learn_agent/tests/test_mission_control.py # Mission Control (D16)
python3 learn_agent/tests/test_coach_service.py   # Coach triggers/persistence (M-P1a)
python3 brain/skills/teacher/tests/test_skill.py  # Teacher skill contract (M-P2a)
python3 learn_agent/tests/test_teacher_integration.py # Teacher teach→upsert→critic + /api/teach
```
Plus: self_check workflow through the runtime; memory files within bounds
(memory_compression skill); log.md gained exactly the lines your work
justified; no new direct-Retriever imports outside gateway/drivers;
`grep -riE 'fable|opus|sonnet|anthropic' brain/runtime/*.py` still empty.
```

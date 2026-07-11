# PLATFORM IMPROVEMENT REPORT — AIOS self-analysis

Generated 2026-07-06, cycle 15. Read: PROJECT_CHARTER.md, AIOS_HANDBOOK.md,
memory/decisions.md (D1–D16), LESSONS.md, memory/state.md,
aios_core/runtime/metrics.jsonl (848 real dispatch records). No code changed
— this is analysis only, per instruction. Every finding below is grounded in
a command actually run against this repository, not inference.

---

## 0. Architecture health (task 1) — current baseline

- **10/10 test suites green** (re-verified live: pipeline, gateway, aios_core,
  runtime, library_skills, console, aios_p0, skill_package, domain_packs,
  mission_control).
- **Memory compliant** (`memory.audit("memory")` → `True`).
- **848 real dispatch records** in `metrics.jsonl`; overall logged success
  rate 73.6% — but this number is itself a finding (§F2): it is polluted by
  intentional test-fixture failures (`no_such_skill`, `tmp_memskill`,
  `flaky`, `pack_probe` account for 149 of the 224 failures), not real
  production health. Filtered to the 10 real production skills, the picture
  is materially healthier than the raw number suggests.
- 11 skills registered (10 real + 1 test fixture — see §F3), 5 corpora
  (2 unignested), 3 executable + 9 documented workflows, 6 SDK APIs, 1
  reference Domain Pack, 2 seeded missions, 8,321 lines of Python.

The platform is structurally sound. The findings below are refinements, not
red flags — nothing here blocks the next milestone.

---

## 1. Findings, prioritized by impact

### 🔴 P1 — START_HERE.md and AIOS_HANDBOOK.md are stale (missing 3 major subsystems)

- **Category:** missing documentation (task 3) + architecture health (task 1)
- **Evidence:** `grep -i "aios_core\|packs/\|mission control" START_HERE.md
  AIOS_HANDBOOK.md` → zero matches in both files. Neither document mentions
  `aios_core/` (D14), Domain Packs (D15), or Mission Control (D16) — three of
  the last four architectural decisions.
- **Rationale:** D13 makes the repository "the sole source of truth" and
  `START_HERE.md` is the literal boot sequence for any new session. A fresh
  model following it *today* would read a component map that stops at P0,
  never learn the SDK exists, never discover Domain Packs, and land on `/app`
  instead of `/` (D16's actual default landing page). This directly
  undermines the platform's central self-documentation promise — the exact
  failure mode the charter exists to prevent.
- **Effort:** Small (~1–2 hours). Both documents already have the right
  shape; this is inserting accurate, already-written material (the
  component map in AIOS_HANDBOOK.md §2 needs the aios_core/packs boxes it's
  missing; START_HERE.md needs the packs/registry + Mission Control landing
  page in its boot sequence).
- **Affected components:** `START_HERE.md`, `AIOS_HANDBOOK.md` (docs only).
- **Success criteria:** a fresh read of `START_HERE.md` → `AIOS_HANDBOOK.md`
  correctly describes: aios_core as the engine, packs as the domain
  extension mechanism, and `/` (not `/app`) as the default landing page.
- **Validation:** re-run the "fresh-engineer audit" pattern used previously
  in this project (an Explore-agent read of the onboarding docs, cross-
  checked against `memory/decisions.md` and the actual registry/routes) and
  confirm zero missing-subsystem gaps this time.

### 🔴 P2 — `metrics.jsonl` has no retention policy and mixes test noise with production telemetry

- **Category:** performance bottleneck (task 8) + technical debt (task 7)
- **Evidence:** file is 189KB / 848 lines after ~2 days of development, with
  **no code anywhere** (`grep -rn "metrics.jsonl" ... | grep -i
  "rotat|prune|trim|truncate"` → zero matches) that bounds, rotates, or
  filters it. Of 848 records, 149 failures come from four skill IDs that
  only exist inside test suites (`no_such_skill`, `tmp_memskill`, `flaky`,
  `pack_probe`) — these are correctly *expected* failures inside tests, but
  they land in the same file `memory.recent_metrics()` reads for
  `architecture_health()`.
- **Rationale:** two compounding problems. (a) Unbounded growth: nothing
  stops this file from growing indefinitely — contrast with every `.md`
  memory file, which the platform *already* enforces a 200-line bound on via
  `memory_compression`. The one file that will grow fastest (one line per
  dispatch, forever) is the one file with no size discipline. (b)
  Correctness: Mission Control's Architecture Health panel
  (`architecture_health()`) computes "recent success rate" from the last 100
  raw entries with no filter — if a test suite ran recently, the dashboard
  can show a misleadingly low number that has nothing to do with real
  platform health. This is a genuine bug hiding behind a "looks like
  observability debt" surface.
- **Effort:** Medium (~half a day). Two independent fixes: (1) rotation —
  either cap the file (keep last N records) or roll over to
  `metrics.jsonl.1` past a size threshold, matching the memory-compression
  precedent already established for `.md` files; (2) correctness — either
  tag test-originated dispatches (a `context` flag threaded through
  dispatch) and filter them out of `architecture_health()`, or write test
  metrics to a separate file entirely (simplest, matches P2's "files are
  source of truth, keep them scoped" pattern).
- **Affected components:** `aios_core/runtime/monitor.py` (record/rotation),
  `learn_agent/mission_control_service.py::architecture_health()`
  (filtering), test suites that dispatch fixture skills (need a way to opt
  out of the shared metrics stream, or accept living in a separate file).
- **Success criteria:** `metrics.jsonl` (or its successor) stays bounded
  under continuous use; `architecture_health()`'s success-rate reflects only
  real skill dispatches, verified by running the full test suite twice in a
  row and confirming the reported rate doesn't move.
- **Validation:** a new test that dispatches a fixture failure, then asserts
  `architecture_health()`'s success rate is unaffected; a size-growth test
  that dispatches 500 synthetic events and asserts the file/records stay
  under a defined cap.

### 🟠 P3 — `echo` test fixture is a permanent member of the production skill registry

- **Category:** technical debt (task 7) + inconsistent APIs (task 6)
- **Evidence:** `brain/skills/registry.json` → `["recursive_planner",
  "book_ingestion", "retrieve_context", "rag_search", "evidence_validation",
  "critic", "evaluator", "memory_compression", "concept_distillation",
  "hypothesis_generation", "echo"]` — 11 entries, one of which
  (`echo`) exists solely to support runtime/composition tests.
- **Rationale:** every "skills_registered" count shown to a user — Mission
  Control's Architecture Health panel, the operator console's health card —
  currently reads 11 when only 10 are real, user-facing capability. This is
  a small but genuine data-integrity issue: a test fixture is silently
  inflating a number presented as platform capability.
- **Effort:** Small (~1 hour). Either (a) move `echo` to a separate
  test-only registry file that test suites point `AIOS_SKILLS_DIR` /
  `Registry(path=...)` at, or (b) tag registry entries with a `test_only:
  true` field and filter it out of `list_skills()`'s default view (keep it
  discoverable for tests that explicitly ask). Option (a) is more consistent
  with the existing `AIOS_SKILLS_DIR` extension seam (§ `aios_core.md` §4)
  and requires no schema change.
- **Affected components:** `brain/skills/registry.json` (remove `echo`),
  a new `brain/skills/test_registry.json` (or similar) for test-only use,
  `brain/tests/test_runtime.py` / `aios_core/tests/test_aios_core.py`
  (repoint their `echo` dispatch at the test registry).
- **Success criteria:** `skill.list_skills()` returns exactly 10 in a
  production context; the echo-dependent tests still pass by pointing at a
  separate fixture registry.
- **Validation:** `len(Registry().list_ids()) == 10` becomes a real
  assertion (currently the codebase asserts `>= 10` specifically to
  tolerate this ambiguity — a smell in itself, worth grepping for after
  the fix and tightening to `== 10`).

### 🟡 P4 — Inconsistent parameter naming for "mission" across the retrieval stack

- **Category:** inconsistent APIs (task 6)
- **Evidence:** three layers, three names for the same concept:
  `second_brain/gateway.py::retrieve(mission_id=...)` →
  `aios_core/sdk/retrieval.py::retrieve(mission=...)` →
  `learn_agent/aios_api.py::retrieve(mission_id=...)` (which calls the SDK
  with `mission=mission_id`). The SDK layer alone renamed the parameter;
  gateway and route layers still say `mission_id`.
- **Rationale:** low urgency today (one maintainer, well-tested), but every
  future Domain Pack, every future route, and every future SDK consumer will
  either copy the SDK's `mission=` or the routes'/gateway's `mission_id=` —
  there's no single correct pattern to copy. Naming drift compounds; better
  to settle it once, deliberately, before Domain Packs 2–4 (finance,
  astrology, product management) each pick a side independently.
- **Effort:** Small (~1–2 hours, mostly mechanical rename + re-run suites).
- **Affected components:** `second_brain/gateway.py`,
  `aios_core/sdk/retrieval.py`, `learn_agent/aios_api.py`,
  `learn_agent/mission_control_api.py` (already only uses the SDK, so it's
  naturally insulated — one more argument for standardizing on the SDK's
  choice, `mission`, and pushing it down rather than up).
- **Success criteria:** one parameter name (`mission`) end to end from route
  to gateway; a grep for `mission_id` inside `aios_core/` and
  `second_brain/gateway.py` returns nothing.
- **Validation:** existing suites (`test_gateway.py`, `test_aios_core.py`,
  `test_aios_p0.py`) already exercise this path — a clean rename should not
  need new tests, just all-green re-runs, which is itself the validation.

### 🟡 P5 — Command-palette JS is duplicated verbatim across two HTML shells (and will triple)

- **Category:** duplicated functionality (task 2)
- **Evidence:** `aios.html` and `mission_control.html` both define
  byte-identical `const j=`, `const el=`, `const esc=` helpers and near-
  identical `openPalette`/`closePalette`/`filterP` implementations (~30–40
  lines each). Neither imports from a shared file — there is no shared JS
  module in the repo at all.
- **Rationale:** this is presentation-layer duplication, not the
  business-logic duplication P10 forbids, so it's lower-severity than a
  backend violation — but it will **triple** the moment a third shell
  appears (the `/legacy` tutor already has its own bespoke JS, and every
  future Domain Pack's UI is a candidate for a fourth copy). Fixing it now,
  while there are only two copies, is far cheaper than fixing it after a
  third and fourth exist.
- **Effort:** Small (~2–3 hours). No build pipeline needed (consistent with
  the "framework-last" philosophy and the vanilla-JS decision in D16): a
  single `learn_agent/static/aios-shared.js` holding `j`/`el`/`esc` +
  the palette component (parameterized by a `commands()` callback), included
  via a plain `<script src="/static/aios-shared.js">` tag in both shells.
- **Affected components:** `learn_agent/static/aios.html`,
  `learn_agent/static/mission_control.html`, new
  `learn_agent/static/aios-shared.js`.
- **Success criteria:** both shells' palette behavior is unchanged (same
  keyboard shortcuts, same visual result) while the helper/palette code
  exists in exactly one file.
- **Validation:** existing tests already check page content for `'⌘K'`,
  `'palette'`, etc. (`test_aios_p0.py::test_shell_page`,
  `test_mission_control.py`) — these should still pass unmodified if the
  extraction preserves behavior; add one new check that both HTML files
  reference the same shared script file (a cheap way to prevent regression
  back into copy-paste).

### 🟡 P6 — Two web frameworks (Flask + FastAPI) serve structurally similar "operator surface" roles

- **Category:** inconsistent APIs (task 6) + technical debt (task 7)
- **Evidence:** `brain/console/app.py` is Flask (port 5052); `learn_agent/
  server.py`, `aios_api.py`, `mission_control_api.py` are FastAPI (port
  8003). Both are dashboards over the same underlying SDK
  (`aios_core.skill/workflow/memory`), built at different times, in
  different frameworks.
- **Rationale:** not urgent — each works, each is tested, and consolidating
  frameworks mid-project has real switching cost for no immediate
  functional gain. Flagging this as a **documented, deliberate choice**
  (keep both, for historical reasons — console predates the AIOS product
  surface) rather than silent drift is the actual ask here: the next time
  someone builds a *third* admin surface, this report should be the
  reference for "we have two for X reason; don't add a third without a
  reason."
- **Effort:** None required now — this is a documentation/decision item,
  not a refactor. (If ever consolidated: Large — a full port of one surface.)
- **Affected components:** none changed; a decisions.md entry closes this.
- **Success criteria:** a `decisions.md` entry exists explaining the
  Flask/FastAPI split so it reads as intentional, not accidental, in any
  future audit.
- **Validation:** N/A (documentation-only).

### 🟢 P7 — `runtime.md`'s manifest key enumeration still undercounts (`purpose` missing from the list) — a **repeat** finding

- **Category:** missing documentation (task 3), **recurrence flag**
- **Evidence:** `brain/runtime/runtime.md` line 27: *"all 11 manifest keys
  present (id, name, version, description, inputs, outputs, memory,
  execution, dependencies, evaluation, tags)"* — `purpose` is absent from
  the enumerated list, despite being present in every real manifest and
  called "recommended" one paragraph later in the same file's authoring
  checklist. This exact gap was already identified in a prior fresh-engineer
  documentation audit this project ran on itself, and was never fixed.
- **Rationale:** low severity on its own, but its persistence *across two
  audits* is the actual signal — a cheap, already-identified, already-
  understood fix that keeps getting deprioritized suggests low-severity doc
  fixes need a lower-friction path to actually landing (e.g., bundled into
  whatever session next touches `runtime.md`, rather than requiring a
  dedicated pass).
- **Effort:** Trivial (~10 minutes — one sentence edit).
- **Affected components:** `brain/runtime/runtime.md` only.
- **Success criteria:** the manifest key list explicitly includes `purpose`
  as the 12th key (matching every real manifest), removing the "11 vs 12"
  ambiguity for good.
- **Validation:** none needed beyond a re-read; optionally, a doc-lint check
  (see P1's validation note) could assert the documented key count matches
  `len(_MANIFEST_REQUIRED) + 1` (the `+1` for `purpose`, which is
  recommended but not currently enforced by `_MANIFEST_REQUIRED`).

### 🟢 P8 — `aios.db` (SQLite mission mirror) is write-only — never queried anywhere

- **Category:** technical debt (task 7)
- **Evidence:** `mission.MissionStore.create()` and `.set_corpora()` write to
  `aios.db`; `grep -rn "SELECT\|\.execute(.*select" learn_agent/*.py
  aios_core/sdk/mission.py` (case-insensitive) returns nothing. Every real
  read (`get()`, `list_all()`) goes through file globs and `mission.json`
  parsing, per P2's own "files are source of truth" principle — exactly as
  intended — which makes the SQLite mirror pure overhead today: written on
  every mutation, read by nothing.
- **Rationale:** this is D4's own precedent working correctly in spirit
  ("SQLite only if size/concurrency demands it") but incompletely in
  practice — the mirror was built ahead of any actual need for it. Not
  harmful (write cost is negligible at current scale), but it's dead code
  by any practical definition, and dead code that looks purposeful
  (a whole schema, a `_db()` connection helper) is worse than dead code
  that's obviously unused, because it invites someone to build on top of
  an assumption ("the mirror must be kept in sync, since it clearly matters")
  that isn't currently true.
- **Effort:** Small either direction: (a) remove the mirror entirely until a
  real read-path need exists (YAGNI, cites D4 directly), or (b) wire one real
  read (e.g., `list_all()` at scale, once mission count is large enough that
  glob+parse is measurably slower) and document why it exists.
- **Affected components:** `aios_core/sdk/mission.py::MissionStore`.
- **Success criteria:** either `aios.db` writes are removed (simplifying the
  class) or a documented, tested read-path exists that the mirror actually
  serves.
- **Validation:** if removed — existing mission tests
  (`test_aios_core.py::test_mission_api`, `test_aios_p0.py`) should pass
  unchanged, proving nothing depended on the mirror; if kept — a new test
  asserting a read query returns the same data as the file-based `get()`.

### ✅ P9 — RESOLVED 2026-07-10 (D19): `distill.py` retired, not exercised

> Resolution: the automated LLM path was DELETED. It had zero callers, no
> workflow/skill dependency, and violated P9 (direct Retriever) and D9 (wrote
> the rendered knowledge_cache). Distillation is the model-agnostic
> `concept_distillation` skill; regression coverage added in
> `test_library_skills.py`. Original finding preserved below for history.

#### (historical) `distill.py`'s LLM path has been an untested "known limit" for 14 consecutive cycles

- **Category:** weak tests (task 4) + technical debt (task 7)
- **Evidence:** `memory/state.md`'s "Known Limits" section has listed
  "distill.py DeepSeek path unexercised" since cycle 1 (this project's very
  first session); it is now cycle 15 and the line is unchanged. `LESSONS.md`
  independently confirms: *"distill.py's automated LLM path remains untested
  (known limit in state.md since cycle 1)."*
- **Rationale:** this is the platform's single longest-lived open item. It
  isn't necessarily wrong to defer — the manual/inline distillation path
  that replaced it (used for all 10 real concepts) works and is tested — but
  14 cycles without a decision either way (fix it, or formally retire the
  automated path) means it now reads as forgotten rather than deferred,
  which is a different thing. `memory/decisions.md`'s entire purpose is to
  convert exactly this kind of ambiguity into a settled choice.
  (This is now the same lesson as P7 at a larger scale: known, cheap-ish,
  and stalled — a pattern worth noticing about how this project's own
  backlog accumulates, not just this one item.)
- **Effort:** Small if retiring (delete the unused path, note why in
  decisions.md); Medium if fixing (one real DeepSeek call in a test,
  requires an API key in the test environment — likely why it's stalled).
- **Affected components:** `second_brain/distill.py`, `memory/state.md`
  (remove from Known Limits either way), `memory/decisions.md` (new entry).
- **Success criteria:** the "known limit" line is gone from state.md,
  replaced by either a passing test or a decisions.md entry explaining the
  retirement.
- **Validation:** if fixed — one integration test gated behind an API-key
  environment check (skip gracefully without a key, matching the existing
  convention of DeepSeek→Anthropic→none resolution elsewhere in the repo).

### 🟢 P10 — The `ai-books` corpus performance claim (LESSONS §3) has never actually been measured

- **Category:** performance bottleneck (task 8)
- **Evidence:** `LESSONS.md` §3 states *"ai-books scale: 25,812 chunks ≈
  seconds of first-query latency per process."* No benchmark script or
  timed test exists anywhere in the repo producing this number — it's an
  engineering estimate, not a measurement, despite being written in the
  declarative, evidence-first voice the rest of LESSONS.md earns through
  actual measured incidents (L3's IDF bug, L4's MaxDD bug, etc., were all
  measured; this one wasn't).
  Cross-referencing the actual metrics.jsonl data (§0): `retrieve_context`
  and `rag_search` dispatches show mean/max times in single-digit
  milliseconds — but every one of those dispatches happened *after* the
  first (cache-warming) query in whatever process ran them, so the
  metrics log itself cannot confirm or refute the "seconds" claim; the slow
  first hit and the cached fast hits are not distinguished anywhere in the
  data.
- **Rationale:** the platform's own philosophy (P6: evaluator before trust;
  "external ground truth beats self-consistency") argues this claim should
  be measured, not asserted — especially since it's used to justify a
  design decision (per-process retriever caching) elsewhere in the docs.
  Low priority because even if the real number is worse than "seconds," the
  mitigating cache already exists and works; this is about closing an
  evidence gap, not fixing a live problem.
- **Effort:** Trivial (~30 minutes) — a one-off timed script:
  cold-import the gateway, time the first `ai-books`-scoped `retrieve()`
  call, record the number in `LESSONS.md` in place of the estimate.
- **Affected components:** `LESSONS.md` (replace estimate with a measured
  figure); no code changes needed unless the real number turns out to be
  a genuine problem, in which case it becomes new, separate work.
- **Success criteria:** `LESSONS.md`'s ai-books latency claim cites an
  actual measured number and the command/script that produced it.
- **Validation:** re-running the same script should reproduce a similar
  number (±reasonable variance) — the validation *is* the measurement
  being reproducible.

---

## 2. Summary table

| # | Finding | Category(ies) | Impact | Effort |
|---|---|---|---|---|
| P1 | START_HERE/HANDBOOK missing aios_core, packs, Mission Control | docs, health | 🔴 Critical | Small |
| P2 | metrics.jsonl unbounded + test-noise pollutes health signal | perf, debt | 🔴 Critical | Medium |
| P3 | `echo` fixture inflates production skill count | debt, API | 🟠 High | Small |
| P4 | `mission` vs `mission_id` naming split (3 layers) | API | 🟡 Medium | Small |
| P5 | Command-palette JS duplicated across 2 shells | duplication | 🟡 Medium | Small |
| P6 | Flask + FastAPI both serve operator-surface roles | API, debt | 🟡 Medium | None (decision only) |
| P7 | runtime.md manifest key count still wrong (repeat) | docs | 🟢 Low | Trivial |
| P8 | aios.db mirror is write-only, never read | debt | 🟢 Low | Small |
| P9 | distill.py LLM path untested for 14 cycles | tests, debt | ✅ RESOLVED (D19) | retired |
| P10 | ai-books latency claim never actually measured | perf | 🟢 Low | Trivial |

**None of these are outdated-skill findings in the strict sense** (task 5):
all 11 registered skills carry current manifests, complete `skill.md`/
`README.md` pairs, and pass their contract tests — the closest thing to an
"outdated skill" is P9 (an unexercised code path inside a skill's supporting
module), listed under weak tests/technical debt instead, since the skill
itself (`concept_distillation` as an agent-type skill) is current and correct.

---

## 3. Roadmap update

The following have been added to `IMPLEMENTATION_PLAYBOOK.md` as milestone
`M-Q1` (Platform Quality — this report's findings) and cross-referenced from
`memory/plan.md`. Per instruction, nothing above has been implemented —
these are queued, prioritized candidates awaiting approval to start, in the
same shape as every other milestone in this project (Objective / Files /
DoD / Exit criteria / Risks).

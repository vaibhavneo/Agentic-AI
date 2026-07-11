# SONNET TASK TEMPLATES — atomic-task sessions

Fill-in prompts for Claude Sonnet sessions executing the Sonnet-scoped work
packages of MIGRATION_EXECUTION_PLAN.md (WP‑0, 2, 3, 5, 6, 7, 8).
Convention source: `model_adapters/Claude_Sonnet.md` — SINGLE atomic task per
session; if it touches >4 files, stop and split; log.md +1 line is part of
done; 30–90 minute sessions with a green suite at each exit.

## The base template

> Read START_HERE.md at ~/Desktop/Agentic AI (boot sequence). Current target:
> **{ONE task id from the catalog below}** as specified in
> MIGRATION_EXECUTION_PLAN.md {WP section}. Write the failing test first,
> implement minimally, run the affected suites plus
> learn_agent/tests/test_aios_p0.py, append one log.md line. Preserve the
> WP's invariants verbatim: {paste invariants bullet}. Gate status: {HUMAN:
> state the H-decision if the WP has one, else "none"}. Stop after this task
> and report what passed.

## Task catalog (one session each)

| task id | WP | scope (files) | test-first target |
|---|---|---|---|
| T0 | WP‑0 | none — run all 12 §V suites, report | n/a (read-only) |
| T2a | WP‑2 | `aios_api.py`: `POST /missions/{slug}/run` + thread/queue status; 409 on concurrent | 409 negative + run-to-STABLE on seeded mission |
| T2b | WP‑2 | `aios_api.py`: status poll/SSE endpoint | cycle rows match metrics.jsonl tail |
| T2c | WP‑2 | `static/aios.html`: Execute tab (criteria editor, cycle table, agent indicator) | existing 25 UI checks + new tab markers |
| T3a | WP‑3 | NEW `brain/skills/mission_tasks/` (full profile) + registry entry | dispatch test incl. MEMORY_VIOLATION negative |
| T3b | WP‑3 | `aios_api.py` task routes + Today's Focus card | plan.md content verified ON DISK after check-off |
| T5 | WP‑5 | retire/adopt legacy `knowledge/` index per H3 | grep-assert: no `knowledge.ingest` imports outside `knowledge/` |
| T6a | WP‑6 | extract inline HTML from `server.py` → `static/legacy.html`; `/ask` → alias | alias payload-shape parity test |
| T6b | WP‑6 | retire `/legacy` (only if H2 = retire) | route-absent test; UI suites green |
| T7 | WP‑7 | `aios.db` per H4 (remove mirror writes OR add tested read path) | removal: suites green with no db; read path: drop→rebuild→identical |
| T8 | WP‑8 | docs truth pass: Q1a + HANDOFF one-liner + HANDBOOK §2 tutor row | `docs/validate_api_reference.py` green; fresh-audit gap check |

## Rules that override any session instinct

1. **Do not take Opus-scoped WPs** (WP‑1, WP‑4). If your task turns out to
   depend on an unimplemented one, STOP and report — do not implement it.
2. **Architectural feelings → text, not code**: if a change seems to need a
   new pattern, propose it in the report and stop (Claude_Sonnet.md
   known-limitation rule).
3. **Skill authoring** (T3a): the skill must be VALID under
   `python3 -m aios_core.skill_sdk.validator <dir> full` with quality ≥85
   BEFORE the registry entry is added (D17). Copy `templates/skill/`.
4. **Memory writes through skills only** where the WP says so — a direct
   file-write in a route is the exact bug class WP‑3 exists to prevent.
5. **Exit report format**: affected suites' tails, the one log.md line you
   appended, files changed (paths), and any HANDOFF-worthy open question.

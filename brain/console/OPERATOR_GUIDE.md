# AI Brain Operator Console — Guide

**Start:** `cd ~/Desktop/"Agentic AI"/brain && python3 console/app.py` → **http://localhost:5052**
(ports: 5050 vedic astro · 5051 stock agent · 5052 this console)

The console is a thin observability layer: every button calls an existing
backend API (runtime dispatcher, registry, monitor, second_brain pipeline).
No logic lives in the UI — if the console shows it, the backend computed it.

## Panels

| panel | what it shows / does | backing API |
|---|---|---|
| **System Health** | skills registered, chunk index size, concept count (+flagged), planner state, last execution | `Registry`, `memory/index/chunks.json`, `metrics.jsonl` |
| **Ingest Documents** | upload `.md`/`.txt` → `memory/uploads/`; Ingest rebuilds the chunk index from the chosen source dir | `dispatch("book_ingestion")` |
| **Search Knowledge** | TF-IDF retrieval; shows source + score per chunk; gibberish honestly returns nothing | `dispatch("retrieve_context")` |
| **Recursive Planner** | run a goal with JSON stability criteria; live cycle table (status, atomic task, per-criterion pass/fail) | `run_loop("recursive_planner")` |
| **Memory Files** | read-only viewer for `memory/*.md` (state, plan, log, decisions, reports) | file read (traversal-blocked) |
| **Execution Log** | last 30 metric entries: skill, ok/failure, duration, retries, memory changes | `metrics.jsonl` |
| **Artifacts** | reports (validation/critic/concepts) + artifacts recorded by executions | `metrics.jsonl` + report files |
| **Validation Status** | pipeline stability (ingest/retrieval/distill) + live critic re-review of all concepts | `second_brain.loop.check()`, `dispatch("critic")` |

## Common workflows

**Add knowledge:** Upload file(s) → select `memory/uploads` → Ingest → Search to confirm.
⚠ The backend keeps ONE chunk index — ingesting a source *replaces* the index.
To return to the curated corpus, re-ingest `wiki/books`.

**Run a planning loop:** enter a falsifiable goal + criteria (each `check` is a
shell command run inside the run's memory root, exit 0 = pass). Watch cycles;
STABLE requires 2 consecutive all-pass cycles. Run memory lands in
`memory/console_runs/` — inspect it via the Memory panel after refresh.

**Health check after changes:** Validation panel → Re-check. `stable: true` +
critic `9/10 supported` is the current known-good baseline (the 1 unsupported
concept is an honest provenance flag, not a defect).

## Tests
`python3 brain/tests/test_console.py` — 30 checks covering every panel's
workflow end-to-end through the same HTTP endpoints the page uses.

## Limits (by design)
- Single planner run at a time (409 if one is running)
- Uploads accept only `.md`/`.txt` (what `book_ingestion` supports)
- The console never writes memory files itself — only skills do, under
  runtime-enforced memory permissions

# Evaluation Contract — recursive_planner v1.0.0

Deterministic wherever possible; every metric names its check. An execution is
**compliant** when all MUST metrics pass; QUALITY metrics grade it.

## MUST metrics (binary, deterministic)

| id | metric | deterministic check |
|---|---|---|
| M1 | Task completion | every `stability_criteria.check` exits true at status=STABLE |
| M2 | Memory consistency | state.md components exist on disk; plan.md checked items have artifacts; no dangling references (scriptable) |
| M3 | Memory updated every cycle | log.md line count ≥ cycle count; state.md `loop_iteration` matches |
| M4 | Loop convergence | STABLE only after 2 consecutive all-pass cycles; no status flapping (STABLE→CONTINUE without new input = violation) |
| M5 | Atomicity | each output_schema result names exactly ONE atomic_task |
| M6 | Compression bound | no memory file > 200 lines; log.md entries ≤ 1 line each |
| M7 | Immutability | decisions.md and log.md histories are append-only across cycles (diffable) |

## QUALITY metrics (scored, mostly deterministic)

| id | metric | check |
|---|---|---|
| Q1 | Retrieval relevance | for seeded test queries, top-1 hit comes from the topically-correct source (exact-match on expected file), ≥ 2/3 |
| Q2 | Planning stability | # of plan re-writes / total cycles ≤ 0.3 (thrash indicator) |
| Q3 | Execution correctness | fraction of Step-5 validations passing on first attempt (report, don't gate) |
| Q4 | Evidence honesty | every flagged-unsupported claim remains flagged (never silently unflagged without new evidence) — diff check |
| Q5 | Refinement ratio | artifact edits : full rewrites ≥ 3:1 (from log) |

## Evaluator implementation
The reference evaluator is the pattern proven in this workspace:
`second_brain/loop.py` (criteria check) + `second_brain/tests/test_pipeline.py`
(stage validation, 20 checks) + `second_brain/critic.py` (evidence
verification). A conforming evaluator for any new deployment re-implements M1–M7
as a script over `memory_root` — no LLM judgment required for MUST metrics.
LLM-as-judge is permitted ONLY for Q-metrics that resist scripting, and its
verdicts must be recorded with the evidence shown to it.

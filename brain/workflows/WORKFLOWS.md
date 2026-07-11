# Workflow Library

Workflows compose SKILLS ONLY (outputs→inputs; `$step.field` binding in
executable `.workflow.json`, prose recipes here for agent-driven ones).
Executor-agnostic. Executable files in this directory run via
`dispatcher.run_workflow(json.load(...))`.

## Executable (files in this dir)
| workflow | chain | status |
|---|---|---|
| corpus_qa | book_ingestion(corpus) → rag_search(scoped) | proven |
| self_check | evaluator(all suites) → critic → memory_compression audit | proven — run after every change |
| plan_then_report | recursive_planner → echo ($binding demo) | proven |

## Recipes (agent executes the chain; each step is a dispatch)

**W-research** — retrieve_context(scoped) → hypothesis_generation(adapter) →
evidence_validation(each claim) → concept_distillation(adapter) → memory_compression.
Exit: every surviving claim has confidence + provenance; unsupported ones flagged not dropped.

**W-learning** — teacher(adapter; socratic/exercise) → concept_store.upsert
(unverified) → critic → retention timestamps. Exit: concepts.json changed measurably. (Full build: M-P2a.)

**W-architecture** — retrieve_context(patterns) → architect(adapter, agent-gated)
→ evaluator(design checklist: charter P-rules as checks) → decisions.md entry.
Exit: design doc + explicit decision record; NO code in this workflow.

**W-coding** — recursive_planner cycle with task_executor = coding adapter:
retrieve → ONE atomic change → evaluator(tests) → memory update. Exit: STABLE
per criteria. This is just the planner contract; listed for discoverability.

**W-refactoring** — evaluator(baseline green) → atomic refactor →
evaluator(same suite, still green; no behavior tests added/changed) → log entry.
Rule: a refactor that needs test changes is a behavior change — use W-coding.

**W-testing** — evaluator skill with a NEW check file; must include ≥1
negative control and ≥1 bounds/dimensional check (LESSONS L4).

**W-debug** — reproduce (failing check) → hypothesis_generation(≥2 rivals,
kill tests) → run kill tests (evaluator) → fix survivor → regression suite →
LESSONS.md entry if the bug taught a rule.

**W-book-ingestion** — corpus_manager.register → book_ingestion(corpus_id) →
gateway smoke query (scoped) → registry stats verified → (optional) critic
re-run to see if flagged concepts gain support (the D11 loop).

**W-mission-planning** — create mission (≥1 corpus, ≥3 tasks, falsifiable
goal) → retrieve_context(goal terms) to seed research notes → recursive_planner
bootstrap cycle → coach picks first Next Action. Exit: mission files scaffolded
and first task selected.

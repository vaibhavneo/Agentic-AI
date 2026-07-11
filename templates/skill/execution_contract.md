# Execution contract — __SKILL_ID__

Executor-agnostic. Steps run in order; no step may be skipped or reordered
(reordering is a MAJOR version change).

## Steps
1. **__STEP_1__** — __pre: …  post: …__
2. **__STEP_2__** — __pre: …  post: …__
3. **__STEP_3__** — __pre: …  post: …__

## Failure handling (mandatory)
| condition | behavior | surfaced as |
|---|---|---|
| __bad/missing input beyond schema__ | __raise ValueError with actionable message__ | EXECUTION_ERROR |
| __precondition file absent__ | __empty-result vs error — CHOOSE and justify__ | __…__ |
Retries: `execution.retries` = __N__ (runtime retries EXECUTION_ERROR only;
deterministic failures must NOT be made retryable to mask bugs).

## Metrics
Every dispatch is recorded by the runtime monitor (elapsed_ms, ok, retries,
memory_changes). Skill-specific numbers worth watching: __e.g. output size, hit counts__.

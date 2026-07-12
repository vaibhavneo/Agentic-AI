# Execution contract — feynman_ask v1.0.0

Executor-agnostic. No step names a model — feynman_agent/'s internal model
call is its own concern.

## Steps
1. **RESOLVE SESSION** — pre: none. Scope `feynman_agent/` itself onto
   `sys.path` (same convention as every other in-process driver), resolve
   `get_session(session_id)` — feynman_agent/'s own lazily-created,
   in-process session store. A test may inject
   `context["_session_instance"]` to skip this (hermetic tests). post: a
   session object with `.ask(question, session_id)`.
2. **INVOKE TUTOR** — call `session.ask(question, session_id)`. post: a dict
   with `answer`/`sources`/`chunks_retrieved`, or a real exception propagates
   as `EXECUTION_ERROR`.
3. **WRAP RESULT** — package `{app: "feynman_agent", answer, sources,
   chunks_retrieved}`. post: conforms to `output_schema.json`.

## Failure handling (mandatory)
| condition | behavior | surfaced as |
|---|---|---|
| `question` missing/empty | schema validation rejects before dispatch | INPUT_INVALID |
| `session.ask` raises | exception propagates unchanged | EXECUTION_ERROR |

Retries: `execution.retries` = 0.

## Metrics
Runtime monitor records elapsed_ms/ok/memory_changes (expected empty) per
dispatch. Skill-specific signal worth watching: `chunks_retrieved` (a value
of 0 across many calls may indicate the knowledge base failed to ingest).

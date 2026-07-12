# Execution contract — stock_agent_analyze v1.0.0

Executor-agnostic. No step names a model — stock_agent/'s internal DeepSeek
calls are its own concern, invisible to this contract.

## Steps
1. **RESOLVE ENDPOINT** — pre: `ticker` present. Resolve the target URL from
   `context["stock_agent_url"]`, else `$STOCK_AGENT_URL`, else
   `http://localhost:5051/api/analyze/stream`. post: a URL string.
2. **CALL OVER HTTP (SSE)** — POST `{ticker}` to the resolved URL, consume
   the SSE stream until a `done` event (or an `error` event). A test may
   inject `context["_sse_collector"]` to stay hermetic (no network). post:
   the terminal `result` event's payload, or a raised `RuntimeError` if the
   stream carried an `error` event or never produced a `result`.
3. **WRAP RESULT** — package `{app: "stock_agent", ticker, result}`. post:
   conforms to `output_schema.json`.

## Failure handling (mandatory)
| condition | behavior | surfaced as |
|---|---|---|
| `ticker` missing/empty | schema validation rejects before dispatch | INPUT_INVALID |
| connection refused / timeout | exception propagates unchanged | EXECUTION_ERROR |
| stream carries an `error` event (e.g. no API key) | raise `RuntimeError` naming the error | EXECUTION_ERROR |
| stream ends with no `result` event | raise `RuntimeError` naming the events actually seen | EXECUTION_ERROR |

Retries: `execution.retries` = 0 (a transient network blip is the caller's
concern to re-dispatch, not this skill's to mask).

## Metrics
Runtime monitor records elapsed_ms/ok/memory_changes (expected empty) per
dispatch. This dispatch's elapsed_ms includes the full stock_agent pipeline
run time (multiple minutes is normal — it is a 7-agent LLM pipeline).

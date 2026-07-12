# Execution contract — health_agent_analyze v1.0.0

Executor-agnostic. No step names a model — health-agent/'s internal LLM call
is its own concern, invisible to this contract.

## Steps
1. **RESOLVE ENDPOINT** — pre: `text` present. Resolve the target URL from
   `context["health_agent_url"]`, else `$HEALTH_AGENT_URL`, else
   `http://localhost:8787/analyze/text`. post: a URL string.
2. **CALL OVER HTTP** — POST `{text}` to the resolved URL as JSON. A test
   may inject `context["_http_post"]` to stay hermetic (no network). post:
   `(status_code, json_body)`, or a raised exception on connection failure.
3. **WRAP RESULT** — if `status >= 400` or the body itself carries an
   `error` key, raise `RuntimeError` naming it. Otherwise package
   `{app: "health_agent", result: json_body}`. post: conforms to
   `output_schema.json`.

## Failure handling (mandatory)
| condition | behavior | surfaced as |
|---|---|---|
| `text` missing/empty | schema validation rejects before dispatch | INPUT_INVALID |
| connection refused / timeout | exception propagates unchanged | EXECUTION_ERROR |
| HTTP status >= 400, or body has an `error` key | raise `RuntimeError` naming the error | EXECUTION_ERROR |

Retries: `execution.retries` = 0.

## Metrics
Runtime monitor records elapsed_ms/ok/memory_changes (expected empty) per
dispatch.

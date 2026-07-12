# Execution contract — vedic_astro_reading v1.0.0

Executor-agnostic. No step names a model — vedic_astro/'s internal LLM calls
are its own concern, invisible to this contract.

## Steps
1. **RESOLVE ENDPOINTS** — pre: `place`/`date`/`time` present. Resolve the
   base URL from `context["vedic_astro_url"]`, else `$VEDIC_ASTRO_URL`, else
   `http://localhost:5050`. post: a base URL string.
2. **GEOCODE** — POST `{place}` to `{base}/api/geocode`. A test may inject
   `context["_geocode_post"]` to stay hermetic. post: `{lat, lon,
   timezone_offset_hours}`, assembled into `birth_info`, or a raised
   `RuntimeError` on a 4xx/5xx status or an embedded `error` key.
3. **READING (SSE)** — POST `{birth_info}` to `{base}/api/reading/stream`; a
   test may inject `context["_reading_sse"]`. Collect every `section` event
   into `sections` keyed by `section.key`, until a `done` event. An `error`
   event, or a stream ending with zero sections, is a failure.
4. **WRAP RESULT** — package `{app: "vedic_astro", birth_info, sections}`.
   post: conforms to `output_schema.json`.

## Failure handling (mandatory)
| condition | behavior | surfaced as |
|---|---|---|
| `place`/`date`/`time` missing/empty | schema validation rejects before dispatch | INPUT_INVALID |
| geocode 4xx/5xx or embedded `error` | raise `RuntimeError` naming it | EXECUTION_ERROR |
| reading stream carries an `error` event | raise `RuntimeError` naming it | EXECUTION_ERROR |
| reading stream ends with no `done` or zero sections | raise `RuntimeError` | EXECUTION_ERROR |
| connection refused / timeout (either step) | exception propagates unchanged | EXECUTION_ERROR |

Retries: `execution.retries` = 0.

## Metrics
Runtime monitor records elapsed_ms/ok/memory_changes (expected empty) per
dispatch. This dispatch's elapsed_ms includes the full 6-agent reading
generation (a multi-minute LLM pipeline is normal).

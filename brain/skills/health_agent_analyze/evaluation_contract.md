# Evaluation contract — health_agent_analyze v1.0.0

Every MUST is deterministic, implemented in `tests/test_skill.py` with a
stubbed HTTP poster (`context["_http_post"]`) — no model, no network.

## MUST checks (deterministic)
- **E1 — happy path returns wrapped result**: a stub poster returning
  `(200, {...})` produces `{app: "health_agent", result: {...}}` with the
  body unchanged.
- **E2 — negative control (missing text)**: an input with no `text` key
  fails schema validation before the driver runs (`INPUT_INVALID`).
- **E3 — upstream error surfaces, is not swallowed**: a stub poster
  returning a 4xx/5xx status, or a 200 body carrying an `error` key,
  propagates as `EXECUTION_ERROR`.

## Discrimination statement (mandatory)
- E1 catches accidental mutation of health-agent/'s own analysis output.
- E2 catches a build that dispatches with empty text, wasting a real call.
- E3 catches a build that treats any 200 response as success without
  checking the body for an embedded `error`.

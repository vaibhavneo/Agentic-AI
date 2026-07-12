# Evaluation contract — stock_agent_analyze v1.0.0

Every MUST is deterministic, implemented in `tests/test_skill.py` with a
stubbed SSE collector (`context["_sse_collector"]`) — no model, no network.

## MUST checks (deterministic)
- **E1 — happy path returns wrapped result**: a stub collector returning a
  `result` event's payload produces `{app: "stock_agent", ticker, result}`
  with `result` unchanged.
- **E2 — negative control (missing ticker)**: an input with no `ticker` key
  fails schema validation before the driver runs (`INPUT_INVALID`).
- **E3 — upstream error surfaces, is not swallowed**: a stub collector
  returning an `error` event (or no `result` at all) propagates as
  `EXECUTION_ERROR`, never a fabricated empty analysis.

## Discrimination statement (mandatory)
- E1 catches accidental mutation of stock_agent/'s own pipeline output.
- E2 catches a build that dispatches with an empty ticker, wasting a real
  multi-agent run on nothing.
- E3 catches a build that treats a missing/error SSE stream as a silent
  success, hiding a real upstream failure (e.g. no API key) from the caller.

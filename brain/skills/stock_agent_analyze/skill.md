# stock_agent_analyze — behavioral contract

## Purpose (mandatory)
Give the Central Orchestrator one typed, dispatcher-enforced way to hand a
ticker to stock_agent/'s existing 7-agent financial analysis pipeline,
without importing stock_agent/'s internals into the orchestrator's process.

## Business problem (mandatory)
stock_agent/ owns `agents/` and `tools/` packages whose bare top-level names
collide with brain/'s own internal packages of the same names — confirmed
empirically, order-dependent (D20). Importing stock_agent/ in-process
alongside brain/ would non-deterministically break one or the other
depending on call order. This skill instead calls stock_agent/'s own running
HTTP server, sidestepping the collision entirely.

## Inputs (mandatory)
- `ticker` (required): the stock ticker symbol, e.g. `AAPL`.

## Outputs (mandatory)
- `app`: always `"stock_agent"`.
- `ticker`: the upper-cased ticker actually analyzed.
- `result`: stock_agent/'s own full pipeline output object, unchanged.

## Determinism (mandatory)
**Not deterministic** — stock_agent/'s 7-agent pipeline makes its own
DeepSeek calls internally. This skill's own logic (HTTP call, SSE parsing,
result wrapping) is fully mechanical; it has no adapter seam of its own and
names no model.

## Hidden-assumption audit (mandatory)
- Assumes stock_agent/'s server is already running and reachable at
  `context["stock_agent_url"]` or `$STOCK_AGENT_URL`, defaulting to
  `http://localhost:5051/api/analyze/stream` — this skill does NOT start
  the server; a connection failure surfaces as `EXECUTION_ERROR`, not a
  silent empty result.
- The endpoint is SSE, not a single JSON response — the driver consumes the
  full stream and extracts the terminal `result` event; a stream that ends
  without one is treated as a failure, not an empty success.
- stock_agent/'s own missing-API-key case returns an `error` SSE event
  (not an HTTP error status) — the driver treats that as `EXECUTION_ERROR`
  too, rather than returning a half-formed "successful" analysis.

## Preconditions / Postconditions (mandatory)
- Pre: `ticker` is a non-empty string; stock_agent/'s server is reachable.
- Post: output validates against `output_schema.json`; no memory files
  changed (stateless).

## When NOT to use (optional but recommended)
For general-purpose or non-financial tasks, use `brain_think` (or let
`central_orchestrator` route automatically).

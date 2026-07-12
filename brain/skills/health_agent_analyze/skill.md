# health_agent_analyze — behavioral contract

## Purpose (mandatory)
Give the Central Orchestrator one typed, dispatcher-enforced way to hand
free-text vitals to health-agent/'s existing threshold + LLM trend
analysis, without importing health-agent/'s internals into the
orchestrator's process.

## Business problem (mandatory)
health-agent/ owns `agents/` and `tools/` packages whose bare top-level
names collide with brain/'s own internal packages of the same names —
confirmed empirically, order-dependent (D20). This skill instead calls
health-agent/'s own running HTTP server, sidestepping the collision.

## Inputs (mandatory)
- `text` (required): free-text vitals, e.g. `"HR=88 BP=145/92 SpO2=94
  patient=P001"`, forwarded to health-agent/'s own `/analyze/text`
  endpoint (which parses it via `extractors/manual_feed.py`) verbatim.

## Outputs (mandatory)
- `app`: always `"health_agent"`.
- `result`: health-agent/'s own analysis output object, unchanged.

## Determinism (mandatory)
**Not deterministic** — health-agent/'s pipeline makes its own LLM call
internally for trend interpretation. This skill's own logic (HTTP call,
result wrapping) is fully mechanical; it has no adapter seam of its own and
names no model.

## Hidden-assumption audit (mandatory)
- Assumes health-agent/'s server is already running and reachable at
  `context["health_agent_url"]` or `$HEALTH_AGENT_URL`, defaulting to
  `http://localhost:8787/analyze/text` — this skill does NOT start the
  server; a connection failure surfaces as `EXECUTION_ERROR`.
- health-agent/'s own parse failures (unparseable vitals text) come back as
  a normal JSON body with an `error` key, not an HTTP error status in every
  case — the driver checks both.
- Free text only, in this skill. health-agent/ also supports screenshot/
  PDF/DOCX extraction (`/analyze/screenshot`, `/analyze/file`) — out of
  scope here; a future `health_agent_analyze_file` skill would wrap those
  separately rather than overloading this one's input shape.

## Preconditions / Postconditions (mandatory)
- Pre: `text` is a non-empty string; health-agent/'s server is reachable.
- Post: output validates against `output_schema.json`; no memory files
  changed (stateless).

## When NOT to use (optional but recommended)
For general-purpose or non-health tasks, use `brain_think` (or let
`central_orchestrator` route automatically).

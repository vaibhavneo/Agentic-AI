# vedic_astro_reading — behavioral contract

## Purpose (mandatory)
Give the Central Orchestrator one typed, dispatcher-enforced way to hand
birth data to vedic_astro/'s existing chart + 6-agent reading pipeline,
without importing vedic_astro/'s internals into the orchestrator's process
or hand-duplicating its geocode->reading sequence at every call site.

## Business problem (mandatory)
vedic_astro/ owns an `agents/` package whose bare top-level name collides
with brain/'s own internal `agents/` package — confirmed empirically (D20).
Separately, vedic_astro/'s own UI is the only place its geocode->reading
sequence exists today; a second hand-written copy would drift. This skill
solves both: it calls vedic_astro/'s own running HTTP server (no import
collision) and keeps the 2-step glue in ONE driver (H-O4: one skill, not
two — no other consumer would ever want a bare "geocode" step on its own).

## Inputs (mandatory)
- `place` (required): birth place string, passed to vedic_astro's own
  geocoder verbatim.
- `date`, `time` (required): birth date/time, in whatever format
  vedic_astro's own `parse_birth_datetime` accepts.

## Outputs (mandatory)
- `app`: always `"vedic_astro"`.
- `birth_info`: the resolved `{date, time, place, lat, lon, tz_offset}` the
  reading was actually computed from (driver-owned, from the geocode step).
- `sections`: every section vedic_astro/'s reading engine emitted
  (`career`, `wealth`, `relationships`, `soul_purpose`, `life_lessons`,
  `synthesis`), each `{title, content}`, unchanged.

## Determinism (mandatory)
**Not deterministic** — vedic_astro/'s 6-agent reading engine makes its own
LLM calls internally. This skill's own logic (geocode, HTTP/SSE glue,
result wrapping) is fully mechanical; it has no adapter seam of its own and
names no model.

## Hidden-assumption audit (mandatory)
- Assumes vedic_astro/'s server is already running and reachable at
  `context["vedic_astro_url"]` or `$VEDIC_ASTRO_URL`, defaulting to
  `http://localhost:5050` — this skill does NOT start the server.
- Geocoding can fail (unknown place) — surfaced as `EXECUTION_ERROR`, never
  a reading computed from a fabricated lat/lon.
- The reading step is SSE with multiple `section` events, not one JSON
  response — the driver collects every section until `done` (or aborts on
  an `error` event); a stream that ends with zero sections is a failure,
  not an empty success.

## Preconditions / Postconditions (mandatory)
- Pre: `place`, `date`, `time` are all non-empty strings; vedic_astro/'s
  server is reachable.
- Post: output validates against `output_schema.json`; no memory files
  changed (stateless).

## When NOT to use (optional but recommended)
For general-purpose or non-astrology tasks, use `brain_think` (or let
`central_orchestrator` route automatically).

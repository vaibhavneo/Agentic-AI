# Evaluation contract — vedic_astro_reading v1.0.0

Every MUST is deterministic, implemented in `tests/test_skill.py` with
stubbed geocode/reading calls (`context["_geocode_post"]`,
`context["_reading_sse"]`) — no model, no network.

## MUST checks (deterministic)
- **E1 — happy path returns wrapped result**: stubbed geocode + stubbed SSE
  section events produce `{app, birth_info, sections}` with the geocoded
  coordinates and every section unchanged.
- **E2 — negative control (missing field)**: an input missing `place`,
  `date`, or `time` fails schema validation before the driver runs
  (`INPUT_INVALID`).
- **E3 — geocode failure surfaces, is not swallowed**: a stub geocode
  returning an `error` key (or 4xx status) propagates as `EXECUTION_ERROR`
  and the reading step is never called.
- **E4 — reading failure surfaces, is not swallowed**: a stub reading
  stream carrying an `error` event, or ending with zero sections,
  propagates as `EXECUTION_ERROR`.

## Discrimination statement (mandatory)
- E1 catches accidental mutation of vedic_astro/'s own coordinates or
  section content.
- E2 catches a build that dispatches with a missing field, wasting a real
  geocode/reading call.
- E3 catches a build that proceeds to the reading step with a fabricated
  lat/lon after a failed geocode.
- E4 catches a build that treats an incomplete or errored reading stream as
  a silent success.

# Evaluation contract — feynman_ask v1.0.0

Every MUST is deterministic, implemented in `tests/test_skill.py` with a
stubbed session (`context["_session_instance"]`) — no model, no network.

## MUST checks (deterministic)
- **E1 — happy path returns wrapped result**: a stub session's `.ask()`
  returning a fixed `{answer, sources, chunks_retrieved}` produces the same
  values unchanged, plus `app: "feynman_agent"`.
- **E2 — negative control (missing question)**: an input with no `question`
  key fails schema validation before the driver runs (`INPUT_INVALID`).
- **E3 — internal failure surfaces, is not swallowed**: a stub session whose
  `.ask()` raises propagates as `EXECUTION_ERROR`.

## Discrimination statement (mandatory)
- E1 catches accidental mutation/truncation of the tutor's own answer or
  source list.
- E2 catches a build that silently defaults `question` to `""` and wastes a
  real tutor call.
- E3 catches a build that swallows exceptions and fabricates an empty answer.

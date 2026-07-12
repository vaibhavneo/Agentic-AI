# Evaluation contract — brain_think v1.0.0

Every MUST is deterministic and implemented in `tests/test_skill.py` with a
stubbed `Brain` instance (`context["_brain_instance"]`) — no model, no network.

## MUST checks (deterministic)
- **E1 — happy path returns wrapped answer**: a stubbed `Brain.think` returning
  a fixed string produces `{app: "brain", answer: <that string>}` unchanged.
- **E2 — negative control (missing task)**: an input with no `task` key fails
  schema validation before the driver ever runs (`INPUT_INVALID`).
- **E3 — internal failure surfaces, is not swallowed**: a stubbed `Brain.think`
  that raises propagates as `EXECUTION_ERROR`, never a fabricated empty answer.

## Discrimination statement (mandatory)
- E1 catches accidental re-summarization or truncation of brain/'s own answer.
- E2 catches a build that silently defaults `task` to `""` and dispatches
  anyway (wasting a real Brain call on nothing).
- E3 catches a build that catches-and-swallows brain/'s exceptions, hiding a
  real failure behind a fake success.

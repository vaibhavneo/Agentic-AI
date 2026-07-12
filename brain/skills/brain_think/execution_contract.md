# Execution contract — brain_think v1.0.0

Executor-agnostic. No step names a model — brain/'s internal model calls are
brain/'s own concern, invisible to this contract.

## Steps
1. **RESOLVE API KEY** — pre: none. Read `context["anthropic_api_key"]`, else
   `os.environ["ANTHROPIC_API_KEY"]`, else empty string (brain/'s own
   constructor produces its own error path on a missing key). post: a string
   (possibly empty) is available for Step 2.
2. **INVOKE BRAIN** — scope `brain/` itself onto `sys.path` (matching
   `brain/cli.py`'s own pattern; the repo root would create a namespace-package
   collision, D20), construct `Brain(api_key=..., verbose=False)`, call
   `.think(task, auto_critique=...)`. A test may inject
   `context["_brain_instance"]` to skip real construction (hermetic tests,
   no network). post: a string answer, or a real exception propagates as
   `EXECUTION_ERROR`.
3. **WRAP RESULT** — package `{app: "brain", answer: str(answer)}`. post:
   conforms to `output_schema.json`.

## Failure handling (mandatory)
| condition | behavior | surfaced as |
|---|---|---|
| `task` missing/empty | schema validation rejects before dispatch | INPUT_INVALID |
| `Brain.think` raises | exception propagates unchanged | EXECUTION_ERROR |
| no API key available | brain/'s own guardrail returns an error STRING (not an exception) — this skill wraps it as a normal answer, since brain/ already decided how to represent that failure to a user | (no effect here) |

Retries: `execution.retries` = 0 (brain/'s own orchestrator has no notion of
being retried mid-task; a caller re-dispatches explicitly if desired).

## Metrics
Runtime monitor records elapsed_ms/ok/memory_changes (expected empty) per
dispatch, same as every other skill.

# Evaluation contract — mission_tasks v1.0.0

Charter P6: build the eval FIRST; external ground truth beats
self-consistency. Every MUST is deterministic, needs no model, and is
implemented in `tests/test_skill.py` against a real temp `plan.md` (ground
truth = the file's own bytes, read back after each call).

## MUST checks (deterministic; tests/ implements each)
- **E1 — create is idempotent by content**: calling `create` twice with the
  identical `description` appends exactly ONE line total; the second call
  returns `changed:false` and the SAME task id as the first. Ground truth:
  `plan.md`'s line count before vs. after both calls.
- **E2 — set_done is idempotent by state**: calling `set_done` with the
  CURRENT state is a no-op (`changed:false`, file bytes unchanged); calling
  it with the OPPOSITE state flips exactly one character in one line.
- **E3 — invalid transitions are typed failures, not silent no-ops**: a
  `task_id` past the end of the file, or pointing at a non-task line (e.g. a
  heading), fails `EXECUTION_ERROR` — it never silently creates or corrupts
  a line.
- **E4 — memory-permission enforcement is real, not assumed**: dispatching
  this skill against a manifest whose write-allowlist has been narrowed to
  exclude `plan.md` (or a driver call that (mis)writes `state.md`) is caught
  as `MEMORY_VIOLATION` by the DISPATCHER — proven by a negative test that
  deliberately writes `state.md` and asserts the dispatch is rejected, not by
  asserting the skill "behaves" (E4 tests the enforcement layer, not intent).
- **E5 — output schema conformance**: every response (`create`/`set_done`,
  no-op/changed) validates against `output_schema.json`; the `changed` flag
  is asserted to match the actual file-bytes diff, not just trusted.

## Quality checks (scored, optional)
- Q1 — the in-process lock's overhead stays negligible under the platform's
  actual single-user load (report, don't gate).

Note: concurrent `set_done` calls against DIFFERENT task ids in the same
mission both landing is NOT a quality/optional check — it is guaranteed by
the driver's per-path lock and asserted as a hard test (see skill.md's
Hidden-assumption audit). Last-write-wins remains the accepted behavior only
for two dispatches targeting the exact SAME task id at the same moment.

## Discrimination statement (mandatory)
- E1 catches a build that appends unconditionally on every `create` call
  (duplicate-line bug on retry/double-click).
- E2 catches a build that always writes on `set_done` regardless of current
  state (defeats retry-safety; also would make E4's negative test noisier).
- E3 catches a build that clamps/wraps an out-of-range `task_id` instead of
  rejecting it (silent data corruption on the wrong line).
- E4 catches a build that writes directly to a memory file bypassing the
  dispatcher's allowlist entirely (the exact anti-pattern this skill exists
  to prevent — P10/D12).
- E5 catches a shape drift a future UI would silently mis-render (e.g. a
  caller checking `response.ok` instead of `response.changed` for
  idempotency, and getting the wrong answer).

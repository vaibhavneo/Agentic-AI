# mission_tasks — behavioral contract

## Purpose (mandatory)
Let a person add a mission task or check one off from the UI, with the write
enforced by the dispatcher rather than trusted to the route handler. Without
this skill, "check a task" has no safe path except a route writing plan.md
directly — the exact anti-pattern PROJECT_CHARTER.md P10/D12 forbid.

## Business problem (mandatory)
Without it, the only way to add/check a mission task is hand-editing
`plan.md` in a text editor, or trusting an API route to write it unaudited
(no memory-permission enforcement, no idempotency, no typed failure on a bad
task id). This skill is the one dispatcher-governed door plan.md's task lines
go through.

## Inputs (mandatory)
- `memory_root` (required): the mission's own directory. Both the read and
  the enforced write allowlist are scoped to it — a call against the wrong
  directory simply can't touch any OTHER mission's files (or any other file
  in this mission's own directory besides plan.md).
- `op` (required): `"create"` or `"set_done"` — see Determinism for the two
  sub-contracts. Conditionally-required fields per op are validated by the
  DRIVER (typed ValueError → `EXECUTION_ERROR`), because this runtime's JSON
  Schema subset has no `if/then` support (see runtime.md).
- `description` (op=create): the task's text, verbatim — never markdown
  checkbox syntax (`- [ ] `), which the driver applies itself.
- `task_id` (op=set_done): the SAME id `mission.get()` already returns per
  task — the task line's 0-indexed position in `plan.md`. This is not a
  separate id space; it IS the line number, by construction of
  `MissionStore._parse_tasks`. Edits elsewhere in plan.md (e.g. a re-plan)
  can shift it — see Hidden-assumption audit.
- `done` (op=set_done): target checkbox state, boolean. The data model is
  binary by construction (`- [ ]` / `- [x]`) — there is no third state to
  transition through, and adding one would be a plan.md format change
  (out of this skill's scope; charter "do not redesign architecture").

## Outputs (mandatory)
`task` is the task's state AFTER the call — for a no-op (idempotent replay),
that's the pre-existing state, not something newly written. `changed` is the
one field callers should trust for "did this call do anything" — a 200/`ok`
response does NOT imply a write happened; a duplicate `create` or a
same-state `set_done` returns `changed:false` on purpose.

## Determinism (mandatory)
**Deterministic.** Same `plan.md` + same inputs ⇒ byte-identical output and,
when `changed:true`, byte-identical resulting file (no timestamps, no
non-deterministic ordering — the only order-sensitive value, `task_id`, is a
pure function of pre-existing line content).
- `create`: dedupes by exact `description` match against ANY existing task
  line (done or not) — the FIRST such match wins if more than one somehow
  exists. No match ⇒ append `- [ ] {description}` as the new last line.
- `set_done`: the target line must already be a task line (`- [ ]`/`- [x]`);
  otherwise `EXECUTION_ERROR`. Requesting the state it's already in is a
  no-op (`changed:false`), never an error — this is what makes retries safe.

## Hidden-assumption audit (mandatory)
- `task_id` is a LINE INDEX, not a stable per-task identifier — inserting or
  removing lines elsewhere in `plan.md` (e.g. a human editing the file, or a
  re-plan cycle) shifts every task_id after the edit point. Checked at
  runtime (`set_done` on a non-task line → typed failure), not silently
  trusted. Callers should re-fetch `mission.get()` after any structural
  plan.md change rather than caching ids.
- `plan.md` may not exist yet for a brand-new memory_root; `create` treats a
  missing file as zero existing lines and writes a fresh file containing
  only the new task line (no header) — mission creation already scaffolds a
  real `plan.md` in the normal path, so this only matters for an unusual
  caller. `set_done` against a missing file has no lines to match, so it
  fails the same "not a task line" check — no special-casing needed.
- The driver serializes its whole read-modify-write per resolved `plan.md`
  path with an in-process `threading.Lock` (module-level, keyed by path) —
  WITHOUT it, two concurrent dispatches against the SAME mission (even
  targeting DIFFERENT task ids) can both read before either writes, and the
  second write silently discards the first (a lost update, not just
  ordering ambiguity — reproduced under real thread concurrency during WP-3
  testing). The lock only covers ONE process; two server PROCESSES writing
  the same file would still race — an accepted, pre-existing single-user
  assumption for plan.md (IMPLEMENTATION_PLAYBOOK.md M-P1c Risks), not one
  this skill introduces or worsens.

## Preconditions / Postconditions (mandatory)
- Pre: `memory_root` names a directory the caller is authorized to write
  (enforced structurally — the dispatcher can only ever detect/permit changes
  under it); `op` is one of the two supported values.
- Post: output validates against `output_schema.json`; if `changed:true`,
  `plan.md` under `memory_root` — and ONLY that file — differs from before
  (any other diff is a `MEMORY_VIOLATION`, dispatcher-enforced, not
  self-policed).

## When NOT to use (optional but recommended)
To read tasks/progress, use `mission.get()` directly (no dispatch needed —
it's a pure read). To run a mission's stability-criteria loop, use
`recursive_planner` via `mission.run()` (WP-2) — this skill only ever touches
the task CHECKLIST lines, never `state.md`/`log.md`/`decisions.md`.

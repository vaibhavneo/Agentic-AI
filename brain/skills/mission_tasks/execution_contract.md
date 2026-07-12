# Execution contract — mission_tasks v1.0.0

Executor-agnostic, fully mechanical (no model/adapter seam — this skill is
`runtime: python`, never `agent`). Steps run in order; no step may be skipped
or reordered (reordering is a MAJOR version change).

## Steps
1. **RESOLVE OPERATION** — pre: `op` is `"create"` or `"set_done"` (schema-
   enforced). Read `plan.md` under `memory_root` (absent ⇒ treated as empty
   for `create`'s bootstrap; see step 2 for `set_done`). Validate the
   op-specific required field is present and non-empty/well-typed:
   `create` needs non-blank `description`; `set_done` needs `task_id` (int)
   and `done` (bool). Missing/blank ⇒ `ValueError` naming the field.
2. **LOCATE OR VALIDATE TASK**
   - `create`: scan every line for the task-line pattern (`- [ ]`/`- [x]`);
     if any line's text exactly equals `description`, that IS the located
     task (jump to step 3 with no pending write).
   - `set_done`: `task_id` must be a valid index into the CURRENT line list
     AND that line must match the task-line pattern. Either failure ⇒
     `ValueError` naming the id (surfaced as `EXECUTION_ERROR`; the API layer
     maps "unknown task" wording to HTTP 404, matching the mission_corpora
     route's existing KeyError→404 precedent).
3. **APPLY IDEMPOTENTLY** — compute the target line content.
   - `create`, task found: target = the FOUND line, unchanged. `changed=False`.
   - `create`, no match: target = new line `- [ ] {description}` appended at
     the end; its id = the line count BEFORE appending. `changed=True`.
   - `set_done`: if the line's current checkbox already equals `done`, target
     = the line unchanged, `changed=False`. Otherwise target = the same line
     text with only the checkbox character flipped, `changed=True`.
4. **WRITE IF CHANGED** — pre: `changed=True` from step 3 (a `False` case
   skips this step entirely — no file touched, so the dispatcher's snapshot
   diff for `plan.md` is empty and trivially satisfies the write allowlist).
   post: `plan.md` rewritten with exactly one line inserted or replaced,
   `\n`-joined, trailing newline preserved. Emit the result per
   `output_schema.json`.

## Failure handling (mandatory)
| condition | behavior | surfaced as |
|---|---|---|
| `op` missing/invalid | schema rejects before the driver runs | INPUT_INVALID |
| `create` with blank/absent `description` | raise ValueError("description required for op=create") | EXECUTION_ERROR |
| `set_done` with absent `task_id`/`done` | raise ValueError naming the missing field | EXECUTION_ERROR |
| `set_done`, `task_id` out of range or not a task line | raise ValueError(f"unknown task_id: {task_id}") | EXECUTION_ERROR |
| any write landing outside `plan.md` | impossible by construction (single `write_text` call on the resolved `plan.md` path) — enforced independently by the dispatcher's own snapshot diff | MEMORY_VIOLATION (never triggered when this skill behaves) |

Retries: `execution.retries` = 0 — every failure above is deterministic;
retrying would reproduce the identical error, not resolve it.

## Metrics
Recorded unconditionally by the runtime monitor. Skill-specific signal worth
watching: `changed` false-rate (a high rate of accepted-but-no-op calls may
mean a caller is polling/retrying instead of reading `mission.get()` first).

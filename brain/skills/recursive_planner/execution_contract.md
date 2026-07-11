# Execution Contract — recursive_planner v1.0.0

The executor performs these 8 steps **in order, every cycle, no exceptions**.
No step references a specific model; any executor honoring this contract is
compliant.

## Step 1 — LOAD MEMORY
Read `state.md` and the active section of `plan.md` from `memory_root`.
Do NOT read `log.md` (unless this cycle is diagnosing a failure) and do NOT
re-read prior artifacts wholesale. If memory files are absent → this is cycle 0:
create them per [memory_contract.md](memory_contract.md) schemas, then set
status=CONTINUE and end the cycle.

## Step 2 — RETRIEVE RELEVANT CONTEXT
Query the retrieval index (or knowledge_sources directly) for ONLY what the
selected task needs. Budget: top-k chunks (k ≤ 5) per query, ≤ 3 queries.
Claims made later in this cycle must trace to retrieved content or the goal
input — never to executor priors alone.

## Step 3 — SELECT NEXT ATOMIC TASK
Take the first unchecked item in plan.md whose dependencies are met. If no
item is actionable: re-plan (respecting plan_depth_limit) — re-planning IS
this cycle's atomic task. If plan is empty and criteria unmet → BLOCKED.

## Step 4 — EXECUTE
Perform exactly ONE atomic task. Produce/modify artifacts as files. Prefer
refinement of existing artifacts over regeneration (Planning Rule 5).

## Step 5 — VALIDATE
Run the task's check (script, test, or file inspection — deterministic
whenever possible). Record pass/fail + evidence. A failed check does NOT roll
back the cycle; it becomes the input to Step 3 next cycle.

## Step 6 — COMPRESS MEMORY
Before writing: reduce this cycle's events to ≤ 1 line for log.md; prune
completed/pruned plan sections; keep state.md a snapshot (current truth only).
Raw transcripts, tool output dumps, and reasoning traces are forbidden in
memory files.

## Step 7 — UPDATE STATE
Write, in this order: log.md (append 1 line) → plan.md (check off / re-plan) →
state.md (overwrite snapshot, bump loop_iteration) → decisions.md (only if an
irreversible choice was made this cycle).

## Step 8 — DECIDE CONTINUATION
Evaluate all stability_criteria via their `check` rules.
- All pass AND all passed last cycle AND no plan/schema change this cycle → **STABLE**, stop.
- Any fail and cycle < max_cycles → **CONTINUE** (loop to Step 1).
- Missing requester-only input → **BLOCKED** (state exactly what, in `blocked_on`).
- cycle = max_cycles or goal falsified → **ABORTED** (log why).

Emit the cycle result conforming to [output_schema.json](output_schema.json).

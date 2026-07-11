# Memory Contract — recursive_planner v1.0.0

All memory lives under `memory_root`. The executor's context window is scratch
space; these files are the system's only durable memory.

## Files the skill MAY READ (any cycle)
| file | when |
|---|---|
| `state.md` | every cycle (Step 1) |
| `plan.md` | every cycle (Step 1) — active section only |
| `decisions.md` | before making a choice that might conflict with one |
| `log.md` | ONLY when diagnosing a repeated failure |
| `index/chunks.json` | via retrieval queries only (Step 2), never wholesale |
| `retrieval.md`, `knowledge_cache.md` / `concepts.json`, `critic_report.md`, `validation_report.md` | when the task concerns them |

## Files the skill MAY UPDATE
| file | policy |
|---|---|
| `state.md` | OVERWRITE — snapshot of current truth; no history |
| `plan.md` | EDIT — check off, re-plan, prune completed sections |
| `log.md` | APPEND-ONLY — exactly one compressed line per cycle |
| `decisions.md` | APPEND-ONLY — irreversible choices only, ≤ 2 lines each |
| `index/`, `concepts.json`, reports | via the corresponding pipeline stage only |

## IMMUTABLE (never modified by this skill)
- The invocation input (goal, stability_criteria) — renegotiating the goal is the requester's act, not the executor's
- Existing `decisions.md` entries — reversal requires a NEW entry citing the old id
- Knowledge sources (ingested books/docs are read-only)
- Past `log.md` lines

## Compression rules (Step 6)
1. **log.md**: one line per cycle — `date cycleID summary` — never paragraphs.
2. **state.md**: replace, don't accumulate. If a fact is no longer true, it leaves the file.
3. **plan.md**: completed phases collapse to a single `[x] Phase N — COMPLETE` line (details live in log.md).
4. **Separation**: decisions ≠ plans ≠ state ≠ log. Content in the wrong file is a contract violation.
5. Any file exceeding ~150 lines must be compressed on the next write that touches it.

## Cycle-0 schemas (created if absent)
- `state.md`: `## Meta` (project, loop_iteration, status, last_updated) + `## Components` table + `## Stability Criteria` checklist
- `plan.md`: `## Objective` + phased checklist (depth ≤ plan_depth_limit) + `## Next Action`
- `decisions.md`: header + dated `D<n>` entries
- `log.md`: header + dated one-liners

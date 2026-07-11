---
name: recursive_planner
version: 1.0.0
description: >
  Execute a long-running goal through a file-persistent recursive planning loop:
  load memory, retrieve only relevant context, perform ONE atomic task, validate,
  compress, update state, and repeat until convergence. Use whenever a task spans
  multiple sessions, exceeds one context window, or must survive executor
  replacement — building software, sustained research, large document analysis,
  book synthesis, or multi-stage financial analysis.
compatibility: any executor with file read/write and (optionally) shell execution
---

# recursive_planner

## 1. Purpose

Long tasks fail in chat-memory systems for three reasons: context drift (early
decisions silently mutate), history bloat (each cycle re-reads everything), and
non-resumability (a new session or different model cannot continue). This skill
solves all three by making **files the only memory**, **retrieval the only way
to access knowledge**, and **one atomic task the only unit of work**. The
executor is stateless between cycles; the system is not.

## 2. Inputs

Required (see [input_schema.json](input_schema.json)):
- `goal` — one-sentence objective with an observable end state
- `memory_root` — directory for the memory files (created if absent)
- `stability_criteria` — list of objectively checkable exit conditions

Optional:
- `knowledge_sources` — dirs/files to ingest for retrieval
- `max_cycles` — hard stop (default 25)
- `plan_depth_limit` — max nesting of plan items (default 3)
- `effort` — low | medium | high (default high); controls exploration breadth, never protocol steps

Constraints:
- `goal` must be falsifiable ("build X that passes tests Y", not "make X better")
- every `stability_criteria` entry must be checkable by a script or file inspection — no "seems good"

## 2b. Determinism

The driver is **mechanically deterministic**: memory bootstrap, criteria
evaluation (each `stability_criteria.check` is a script/file inspection),
convergence tracking, and memory writes contain no RNG and iterate in a fixed
order — given identical inputs AND identical `context["task_executor"]`
outputs, the cycle is byte-reproducible. Its driver lines are 100% test-
covered (`aios_core.runtime.drivers.recursive_planner_driver`).

Nondeterminism enters ONLY through the pluggable `context["task_executor"]`
(the atomic-task reasoning seam — usually an LLM). This is the platform's
standard split (charter P8): the driver is the deterministic unit; reasoning
is adapter-injected. The capability descriptor's `deterministic: true` refers
to this mechanical layer — end-to-end reproducibility holds iff the injected
executor is itself deterministic.

## 3. Outputs

Per cycle (see [output_schema.json](output_schema.json)): a result object with
`status` ∈ `CONTINUE | STABLE | BLOCKED | ABORTED`, the atomic task performed,
artifacts produced, memory files updated, and validation results.

Expected artifacts: code/documents/data the goal demands — every claim of
completion must point at a file.

Expected memory updates per cycle: `state.md` (overwritten), `log.md` (one line
appended), `plan.md` (item checked off or re-planned). See
[memory_contract.md](memory_contract.md).

Status semantics:
- `CONTINUE` — cycle done, criteria not all met
- `STABLE` — all stability criteria pass on TWO consecutive cycles
- `BLOCKED` — needs input only the requester can provide (say exactly what)
- `ABORTED` — max_cycles reached or goal falsified

## 4. Planning Rules (model-independent)

1. **One atomic task per cycle.** An atomic task changes a small set of files and is validatable in isolation.
2. **Retrieve before reasoning.** Never answer from executor priors when memory or knowledge sources can be queried; base claims on retrieved content.
3. **Never expand full history.** Read `state.md` + the relevant plan section; `log.md` is append-only and consulted only when diagnosing.
4. **Plans stay shallow.** Max depth `plan_depth_limit`; deeper nesting means the task decomposition is wrong.
5. **Prefer refinement over regeneration.** Edit existing artifacts; full rewrites require a logged decision entry.
6. **Validate every stage with evidence.** A step is done when its check passes, not when the executor says so.
7. **Honest flags over gamed scores.** If evidence can't support a claim, flag it and plan to acquire evidence — never adjust the verdict.
8. **Stop on convergence.** Two consecutive cycles with all criteria passing and no plan/schema changes ⇒ `STABLE`, stop.
9. **Decisions are irreversible by default.** Reversing a `decisions.md` entry requires a new entry citing the old one.
10. **Compress at write time.** Memory files store summaries and current truth, never transcripts.

## 5. Protocol

Follow [execution_contract.md](execution_contract.md) exactly — 8 steps per
cycle, no skipping, no reordering. Memory access is governed by
[memory_contract.md](memory_contract.md). Success is measured by
[evaluation.md](evaluation.md).

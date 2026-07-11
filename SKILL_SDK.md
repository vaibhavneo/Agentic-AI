# SKILL SDK — the AIOS Skill Development Kit

The complete system for designing, implementing, validating, versioning, and
maintaining AIOS skills — by any compliant model, with no conversation
history. Assumes PROJECT_CHARTER.md has been read.

**The SDK in one paragraph:** copy [`templates/skill/`](templates/skill/),
fill it following [`SKILL_AUTHOR_GUIDE.md`](SKILL_AUTHOR_GUIDE.md), validate
with `python3 -m aios_core.skill_sdk.validator <dir> full` until VALID,
score with `python3 -m aios_core.skill_sdk.quality <dir>`, register per
[`SKILL_MARKETPLACE.md`](SKILL_MARKETPLACE.md), compose per §3 below.
The normative runtime behavior lives in [`SKILL_RUNTIME_SPEC.md`](SKILL_RUNTIME_SPEC.md).

---

## 1. Canonical skill structure (Part 1 — the specification)

Every **new** skill is a folder with exactly this layout (the "full profile").
The pre-SDK library (2026-07) satisfies a reduced "core profile" and is
tracked as migration debt — see SKILL_VALIDATION.md §Profiles.

```
<skill_id>/
  README.md               ── the 30-second card. GENERATED-STYLE summary of the
                             manifest: runtime type, steps, memory, deps, version.
                             Audience: someone deciding whether to use this skill.
  manifest.json           ── THE machine contract (12 keys — see §2). The only
                             file the runtime itself reads. Single source of
                             truth for id/version/schemas/memory/entrypoint.
  skill.md                ── the behavioral contract in prose. Semantics the
                             schemas can't express: field meaning, invariants,
                             determinism claim, hidden-assumption audit,
                             pre/postconditions. Audience: the implementer and
                             the reviewer.
  execution_contract.md   ── ordered steps with per-step pre/post, the failure-
                             handling table, and retry policy. Reordering or
                             removing a step = MAJOR version.
  memory_contract.md      ── intent behind the manifest memory block (which the
                             dispatcher ENFORCES via sha1 diff — this file
                             explains WHY each allowlist entry exists).
                             Mandatory when the skill declares any write.
  evaluation_contract.md  ── MUST checks (deterministic, ground-truthed),
                             quality checks, and the discrimination statement
                             ("what wrong implementation would each check
                             catch"). Written BEFORE the driver (charter P6).
  input_schema.json       ── JSON-Schema subset (see SKILL_RUNTIME_SPEC.md §4)
  output_schema.json         for inputs/outputs. May be inlined in the manifest
                             (schema_inline) for trivial shapes; separate files
                             are the default for reviewability.
  examples/               ── ≥1 happy-path + ≥1 negative example, each a JSON
                             file {description, inputs, expected_output|
                             expected_failure, notes}. Examples are EXECUTABLE
                             documentation: tests must replay every one.
  tests/                  ── standalone python scripts (`python3 file` → exit
                             code + "ALL PASS"), one assertion per evaluation
                             MUST, idempotent, evidence printed next to verdicts.
  CHANGELOG.md            ── newest-first version history; top entry MUST match
                             manifest.version (validated).
```

**Mandatory vs optional:** every file above is mandatory in the full profile
except: separate schema files (inline allowed), and `memory_contract.md` for
fully stateless skills (`root_param: null`, no writes). Optional additions:
`assets/` (fixtures), extra contract appendices. `skill.md`'s mandatory
sections: Purpose, Business problem, Inputs, Outputs, Determinism,
Hidden-assumption audit, Preconditions/Postconditions. Optional: "When NOT
to use" (recommended).

## 2. The manifest (12 keys, all required for SDK skills)

`id · name · version · description · purpose · tags · inputs · outputs ·
memory · execution · dependencies · evaluation` — full field semantics in
SKILL_RUNTIME_SPEC.md §3. Note `purpose` (WHY it exists) is distinct from
`description` (WHAT it does); both one sentence; the validator rejects
manifests missing either.

## 3. Skill composition (Part 7 — how skills become workflows)

Canonical chains and worked recipes: [`brain/workflows/WORKFLOWS.md`](brain/workflows/WORKFLOWS.md).
Mechanics (implemented in `aios_core.workflow`, contract-tested):

- **Execution ordering** — `run_workflow(wf)` executes `steps[]` strictly in
  order. A step's inputs may bind any prior step's output via
  `"$stepname.field.path"` (resolved recursively through dicts/lists).
  Cyclic execution (loops) is NOT expressed in workflow files — cyclic skills
  (recursive_planner) are driven by `run_loop()` until STABLE|BLOCKED|ABORTED.
- **Dependency resolution** — per-skill `dependencies` are resolved
  topologically by the registry at dispatch (DISCOVER stage), with semver
  constraints; unsatisfiable → typed DEPENDENCY_UNRESOLVED, never best-effort.
- **Retry policy** — per-skill via manifest `execution.retries`; the runtime
  retries EXECUTION_ERROR only (deterministic failures like INPUT_INVALID or
  OUTPUT_INVALID never retry — retrying them would mask bugs). Workflows do
  not add a second retry layer.
- **Rollback** — there is no automatic transactional rollback, deliberately:
  durable state lives in memory files (P1/P2), so recovery = re-running from
  files, and every step's memory writes are permission-bounded. Workflows are
  **fail-fast with partial results returned** (`{ok: false, failed_step,
  results[]}`) — the caller sees exactly which steps completed. Skills whose
  writes must be undoable write derived/rebuildable artifacts (P2), not
  destructive mutations; append-only files (log/decisions) are never rolled back.
- **Shared memory** — skills sharing a `memory_root` share state through
  FILES, under each skill's own enforced allowlist. No in-process shared
  blackboard exists between workflow steps; `$step.field` binding is the only
  in-band channel.
- **Artifact passing** — outputs are JSON-serializable dicts; large artifacts
  are written to disk by the producing skill and passed BY PATH in the output
  (see book_ingestion's `index_path` → historic corpus_qa binding).
- **Error propagation** — a failed step stops the chain; its
  `DispatchResult` (typed failure + detail) is embedded in the workflow
  result. Metrics are recorded for failed steps too (observability is
  unconditional).

## 4. The rest of the kit

| document | covers |
|---|---|
| [SKILL_AUTHOR_GUIDE.md](SKILL_AUTHOR_GUIDE.md) | how to design/decompose/implement + the engineering rules (Part 3 + 9) |
| [SKILL_RUNTIME_SPEC.md](SKILL_RUNTIME_SPEC.md) | normative runtime contract: lifecycle, manifest, schemas, failures, versioning |
| [SKILL_VALIDATION.md](SKILL_VALIDATION.md) | the 9-stage validator + 8-category quality score (Parts 4 + 5) |
| [SKILL_MARKETPLACE.md](SKILL_MARKETPLACE.md) | registry: registration→deprecation lifecycle (Part 8) |
| [MODEL_EXECUTION_GUIDE.md](MODEL_EXECUTION_GUIDE.md) | per-model execution guidance (Part 6) |
| [templates/skill/](templates/skill/) | the canonical layout as fill-in files (Part 2) |
| [CAPABILITY_DESCRIPTOR.md](CAPABILITY_DESCRIPTOR.md) | optional advisory `capability.json`: routing hints, semantic I/O, verified quality reqs |
| [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md) | the SDK's self-test: a skill recreated from docs alone (Part 10) |

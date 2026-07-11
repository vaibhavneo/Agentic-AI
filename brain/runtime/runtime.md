> **NOTE (v1.1):** the runtime code moved to `aios_core/runtime/` and is now
> fronted by the AIOS Core SDK. This document still describes the lifecycle and
> manifest spec accurately. See `aios_core/aios_core.md` and `aios_core/MIGRATION.md`.
> `brain/runtime/` now holds backward-compat shims only.

# Skill Runtime — Architecture (v1.0.0)

Model-agnostic execution infrastructure for the Brain Skill Library. Executes
any skill from five inputs only: **manifest · execution contract · input
schema · output schema · memory contract**. No conversation history, no
model-specific behavior — reasoning enters exclusively through pluggable
adapters.

## Modules
| module | responsibility |
|---|---|
| [lifecycle.py](lifecycle.py) | 9-step lifecycle, typed failures, pre/postconditions, `DispatchResult` |
| [registry.py](registry.py) | registration · discovery (query/tag) · version lookup · topological dependency resolution · semver compatibility (`>=X <Y` grammar) |
| [validator.py](validator.py) | dependency-free JSON-Schema subset (type/required/enum/bounds/items/additionalProperties + default injection) |
| [executor.py](executor.py) | runs `runtime.type: python` entrypoints; `type: agent` contract-cards require `context["agent_adapter"]` — a typed NOT_EXECUTABLE otherwise |
| [monitor.py](monitor.py) | sha1 memory snapshots + diff; metrics.jsonl (time, ok, confidence, memory changes, artifacts) — recorded on success AND failure |
| [dispatcher.py](dispatcher.py) | the facade: `dispatch()` (9 steps), `run_workflow()` (output→input binding), `run_loop()` (cyclic skills to terminal status) |
| drivers/ | reference python drivers: `recursive_planner_driver` (mechanical contract steps; atomic-task reasoning delegated to `context["task_executor"]`), `echo_driver` (test) |

## The 9-step lifecycle (per dispatch)
1. **DISCOVER** — id resolves in registry; dependencies resolve topologically, versions compatible
2. **LOAD_MANIFEST** — all 12 manifest keys present (id, name, version, description, purpose, inputs, outputs, memory, execution, dependencies, evaluation, tags)
3. **VALIDATE_INPUT** — schema check; declared defaults injected
4. **CHECK_MEMORY_PERMS** — `memory.root_param` input present; allowlists loaded
5. **EXECUTE** — entrypoint/adapter runs; pre-execution memory snapshot taken
6. **VALIDATE_OUTPUT** — schema check on the raw result
7. **VERIFY_MEMORY** — actual file changes ⊆ `write ∪ append_only` patterns; anything else = MEMORY_VIOLATION (result marked failed even though output validated)
8. **RECORD_METRICS** — unconditional, success or failure
9. **RETURN** — `DispatchResult`; no exceptions escape

**Failure handling:** every failable step has exactly one typed code
(SKILL_NOT_FOUND, MANIFEST_INVALID, INPUT_INVALID, MEMORY_ROOT_INVALID,
NOT_EXECUTABLE, EXECUTION_ERROR, OUTPUT_INVALID, MEMORY_VIOLATION,
DEPENDENCY_UNRESOLVED). Fail-fast; metrics still recorded; partial state is
whatever the skill's own memory contract left on disk (memory files, not the
runtime, are the recovery mechanism — by design).

## Manifest standard (every future skill)
See [../skills/recursive_planner/manifest.json](../skills/recursive_planner/manifest.json)
for the reference instance. Required keys: `id, name, version, description,
inputs{schema|schema_inline}, outputs{schema|schema_inline},
memory{root_param, read, write, append_only, immutable},
execution{contract, steps, runtime{type, entrypoint?}}, dependencies[{id,
version, optional}], evaluation{contract?, must[]}, tags[]`.
Registry entries carry either `manifest_path` or an inline `manifest`.

## Composition
`run_workflow()` executes steps sequentially; `"$stepname.field.path"` strings
in a step's inputs bind to prior outputs (resolved recursively through dicts/
lists). Fail-fast with partial results. Cyclic skills use `run_loop()`, which
re-dispatches until STABLE / BLOCKED / ABORTED.

## Model-agnosticism guarantees
- runtime code names no model or vendor (enforced by test)
- `type: agent` skills receive reasoning via `context["agent_adapter"]`;
  `recursive_planner` receives it via `context["task_executor"]` — swap the
  callable, swap the model, behavior contract unchanged
- all state in files; a dispatch sequence can resume after process death from
  memory files alone

## Architecture diagram

```
                       ┌─────────────────────────────┐
  caller / workflow ──▶│         dispatcher          │──▶ DispatchResult
                       └──┬───────┬───────┬──────┬───┘
              1-2 DISCOVER│  3,6  │ 4,7   │  5   │ 8
                       ┌──▼──┐ ┌──▼───┐ ┌─▼────┐ ┌▼──────┐
                       │ reg │ │valid.│ │ mem  │ │monitor│
                       │istry│ │ator  │ │perms │ │metrics│──▶ metrics.jsonl
                       └──┬──┘ └──────┘ └─┬────┘ └───────┘
                 manifests│               │snapshots (sha1 diff)
                       ┌──▼───────────┐ ┌─▼──────────────┐
                       │skills/*/     │ │  memory_root/  │  ◀── notebook-first
                       │manifest.json │ │ state·plan·log │      memory (files)
                       └──────────────┘ └────────────────┘
                              │
                       ┌──────▼───────────────────────────┐
                       │            executor              │
                       │  type:python → entrypoint fn     │
                       │  type:agent  → context adapter ◀─┼── any model plugs
                       │  (retries: EXECUTION_ERROR only) │    in here
                       └──────────────────────────────────┘

  composition:  run_workflow(steps)  outputs ──"$step.field"──▶ next inputs
  cyclic:       run_loop(skill)      re-dispatch until STABLE|BLOCKED|ABORTED
```

## Extension points

1. **New executor types** — `executor.execute()` switches on `runtime.type`.
   Add e.g. `type: "http"` (remote skill) or `type: "subprocess"` there; nothing
   else changes.
2. **Reasoning adapters** — `context["agent_adapter"]` (agent-type skills) and
   `context["task_executor"]` (recursive_planner's atomic step). This is the
   model seam: Fable, Opus, Sonnet, a human, or another program — anything
   callable. Outputs are still schema-validated, so a weaker executor cannot
   silently degrade the contract.
3. **Retrieval backends** — drivers import `second_brain.retrieve.Retriever`;
   swap for embeddings behind the same `retrieve(query, top_k)` signature
   (RAG-maturity-ladder rule: only when TF-IDF measurably fails).
4. **Registry sources** — `Registry(path)` takes any registry.json; federating
   multiple libraries = merging entry lists.
5. **Retry/backoff policy** — `execution.retries` in the manifest; backoff
   strategies would extend the dispatcher's attempt loop only.

## Adding a new skill (checklist)

1. `mkdir brain/skills/<id>/` → write `skill.md` (purpose, inputs, outputs, contract).
2. Write `manifest.json` — all 12 required keys incl. `purpose` (SKILL_RUNTIME_SPEC.md §3);
   schemas inline or as files. Copy recursive_planner's as the reference.
3. Deterministic behavior? → write a driver fn in `runtime/drivers/` and set
   `runtime: {type: python, entrypoint: "runtime.drivers.<mod>:<fn>"}`.
   Generative? → `runtime: {type: agent}` (adapter-gated).
4. Declare `memory` allowlists honestly — the dispatcher ENFORCES them (writes
   outside `write ∪ append_only` fail the dispatch).
5. Add the entry to `skills/registry.json` (or `Registry.register(..., persist=True)`).
6. Add a dispatch test in `brain/tests/test_library_skills.py` — including one
   failure-path check (bad input, not-found, or unsupported claim).
7. Run `brain/tests/` — both suites must stay green.

## Versioning strategy

- **Skills**: semver per manifest. Breaking = schema field type/requiredness
  changes, memory-contract narrowing→widening, execution-step reordering.
  Compatible = new optional inputs, extra output fields, added tags/examples.
  Registry constraint grammar: `>=X.Y.Z <A.B.C`, `=X.Y.Z`, `*`.
- **Runtime**: v1.1.0 (retries + purpose field + this doc — compatible
  additions over v1.0.0). The runtime never auto-upgrades a skill: dependency
  constraints pin majors, and `get_manifest(id, constraint)` fails loudly on
  incompatibility rather than best-effort matching.
- **Metrics**: metrics.jsonl entries are append-only and versionless by design;
  new fields may appear (readers must tolerate unknown keys).

# SKILL RUNTIME SPEC — normative contract (v1.1)

The single normative statement of how skills execute. Implementation:
`aios_core/runtime/` (SDK facade: `aios_core.skill/workflow/agent/memory/
retrieval/mission`). Narrative architecture + diagrams: `brain/runtime/
runtime.md` and `aios_core/aios_core.md` — if those documents ever disagree
with this one, THIS one wins and the others get fixed.

## 1. Execution model

A skill executes only via `dispatch(skill_id, inputs, context, registry=,
version_constraint=)` → `DispatchResult`. The dispatcher walks 9 stages, in
order, no exceptions escaping:

| # | stage | fails as |
|---|---|---|
| 1 | DISCOVER — id resolves; dependencies topologically resolve within semver constraints | SKILL_NOT_FOUND · DEPENDENCY_UNRESOLVED |
| 2 | LOAD_MANIFEST — manifest complete | MANIFEST_INVALID |
| 3 | VALIDATE_INPUT — schema check, defaults injected | INPUT_INVALID |
| 4 | CHECK_MEMORY_PERMS — `memory.root_param` input present when declared | MEMORY_ROOT_INVALID |
| 5 | EXECUTE — python entrypoint or agent adapter; sha1 memory snapshot before | NOT_EXECUTABLE · EXECUTION_ERROR |
| 6 | VALIDATE_OUTPUT — schema check on the raw result | OUTPUT_INVALID |
| 7 | VERIFY_MEMORY — actual file changes ⊆ `write ∪ append_only` | MEMORY_VIOLATION |
| 8 | RECORD_METRICS — unconditional (success and failure) → metrics.jsonl |
| 9 | RETURN — DispatchResult {ok, output, failure, failure_detail, metrics, memory_changes, violations} |

Retries: `execution.retries` (default 0) applies to EXECUTION_ERROR **only**;
attempts/retries recorded in metrics. Deterministic failures never retry.

## 2. Executor types & the model seam

- `runtime.type: "python"` — `entrypoint: "pkg.module:function"`,
  `fn(inputs, context) -> dict`. Deterministic by convention (author guide §4).
- `runtime.type: "agent"` — requires `context["agent_adapter"] =
  callable(manifest, inputs, context) -> dict`; absent → NOT_EXECUTABLE.
  The adapter is the ONLY seam a model enters through (charter P8); adapter
  output is still stage-6 schema-validated — a weak model cannot silently
  degrade a contract.
- Cyclic skills additionally take `context["task_executor"]` (see
  recursive_planner's package — the flagship reference).
- New executor types (http, subprocess) extend `executor.execute()`'s switch
  only.

## 3. Manifest — 12 required keys

`id` (== folder name, snake_case) · `name` · `version` (semver) ·
`description` (WHAT, one sentence) · `purpose` (WHY, one sentence) · `tags[]`
· `inputs{schema|schema_inline}` · `outputs{schema|schema_inline}` ·
`memory{root_param, read[], write[], append_only[], immutable[]}` ·
`execution{contract, steps[], retries?, runtime{type, entrypoint?}}` ·
`dependencies[{id, version, optional}]` · `evaluation{contract, must[]}`.

Historical note: pre-SDK docs said "11 keys + purpose recommended"; the SDK
makes `purpose` required for all new skills (validator V2b enforces 12).

## 4. Schema dialect

The validator implements a deterministic JSON-Schema subset: `type, required,
properties, additionalProperties, items, enum, minLength, minItems, minimum,
maximum, default` (defaults are INJECTED into inputs at stage 3). Do not use
constructs outside this subset — they will silently not validate. `oneOf`/
`anyOf`/`$ref` are unsupported by design (simplest correct thing; extend the
validator first if genuinely needed, with tests).

## 5. Memory enforcement

The manifest memory block is a hard sandbox, not advice: the dispatcher
sha1-snapshots `memory_root` before/after EXECUTE and fails the dispatch on
any change outside `write ∪ append_only` — even if the output validated.
Append-only files must only grow (log.md, decisions.md discipline). Stateless
skills declare `root_param: null` and get no memory diff pass.

## 6. Registry & versioning

`Registry(path)` over a registry.json (default `brain/skills/registry.json`,
overridable via `AIOS_SKILLS_DIR`; composite in-memory registries via
`Registry.register()` + `dispatch(registry=)` — the Domain-Pack seam, D15).
Constraint grammar: `>=X.Y.Z <A.B.C`, `=X.Y.Z`, `*`. Version rules:
SKILL_AUTHOR_GUIDE.md §8. The runtime never auto-upgrades: incompatible
constraints fail loudly at DISCOVER.

## 7. Composition

`run_workflow` (ordered steps, `$step.field` binding, fail-fast with partial
results) and `run_loop` (cyclic, until STABLE|BLOCKED|ABORTED). Full
semantics incl. rollback/shared-memory/artifact rules: SKILL_SDK.md §3.

## 8. Observability

Every dispatch appends one JSON line to metrics.jsonl: ts, skill, version,
ok, elapsed_ms, attempts, retries, confidence (if the output carries one),
memory_changes, artifacts, failure. Readers must tolerate unknown keys.
Known open issue: no retention policy + test-noise mixing — tracked as
M-Q1b in IMPLEMENTATION_PLAYBOOK.md; do not build features that depend on
raw metrics.jsonl being clean until that lands.

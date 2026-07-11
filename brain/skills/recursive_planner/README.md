# Skill: recursive_planner v1.0.0

**Purpose:** Long tasks fail via context drift, history bloat, and non-resumability; this makes files the only memory and one atomic task the only unit of work.

**What it does:** File-persistent recursive planning loop: load memory, retrieve, execute ONE atomic task, validate, compress, update state, repeat until convergence.

| aspect | value |
|---|---|
| runtime | python → `runtime.drivers.recursive_planner_driver:run` |
| execution steps | LOAD MEMORY → RETRIEVE RELEVANT CONTEXT → SELECT NEXT ATOMIC TASK → EXECUTE → VALIDATE → COMPRESS MEMORY → UPDATE STATE → DECIDE CONTINUATION |
| inputs / outputs | schemas in [manifest.json](manifest.json) (`inputs`/`outputs`; canonical machine format — see PROJECT_CHARTER.md §5) |
| memory permissions | root=`memory_root` · write: ['state.md', 'plan.md', 'index/*', '*.md', '*.json'] · append-only: ['log.md', 'decisions.md'] · immutable: [] |
| dependencies | retrieve_context >=1.0.0 <2.0.0 (optional), memory_compression >=1.0.0 <2.0.0 (optional), evaluator >=1.0.0 <2.0.0 (optional) |
| failure modes | typed runtime failures (see brain/runtime/lifecycle.py): INPUT_INVALID, NOT_EXECUTABLE, EXECUTION_ERROR (retries=0), OUTPUT_INVALID, MEMORY_VIOLATION |
| success metrics | contract card [skill.md](skill.md); evaluation refs: evaluation.md ['M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7'] |
| compatibility | any executor honoring the runtime contracts (Charter P8); registry constraint grammar `>=X.Y.Z <A.B.C` |
| tests | brain/tests/test_library_skills.py (dispatch + failure-path) + tests/ in this folder |

Behavioral contract and design rationale: [skill.md](skill.md).

## Full package
This flagship skill ships complete contracts: [execution_contract.md](execution_contract.md), [memory_contract.md](memory_contract.md), [evaluation.md](evaluation.md), [input_schema.json](input_schema.json), [output_schema.json](output_schema.json), examples/, tests/.

<!-- GENERATED from manifest.json — regenerate via the script in git history / handoff notes; edit manifest.json + skill.md, not this file. -->

## Portability guarantees
Depends ONLY on: input schema · memory contract · execution contract.
Depends NEVER on: model identity, prompt wording, hidden reasoning,
conversation history. An executor switched mid-task resumes from memory
files alone (property exercised during this package's own construction).

## Versioning (semantic) — v1.0.0
- **Breaking changes (major):** renaming/removing memory files or their
  required sections; changing a schema field's type or requiredness;
  altering the 8-step cycle order; weakening an immutability rule.
- **Compatible changes (minor):** new optional input fields; additional
  metrics in evaluation.md; new examples; additional OPTIONAL memory files;
  stricter (never looser) validation.
- **Patches:** wording/typo/test additions with no contract meaning change.

## Future extensions (roadmap, non-binding)
- 1.1: pluggable retrieval backends behind the same retrieve(query, k) seam
- 1.2: multi-executor handoff manifest (two models alternating cycles)
- 2.0: structured memory promoted from optional to required — breaking

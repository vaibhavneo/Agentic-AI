# MODEL EXECUTION GUIDE — running & authoring AIOS skills per model

One architecture, zero per-model variants (charter P8): every model executes
the same contracts through the same runtime; output schemas equalize quality
floors (stage-6 validation rejects what a weaker pass produces, regardless of
who produced it). This guide tunes EFFORT ALLOCATION only. General repo
conduct per model: `model_adapters/<Model>.md` (read yours first). This file
adds the skill-specific layer.

## Universal execution protocol (all models)

1. Boot via START_HERE.md; never begin from priors.
2. To RUN a skill: `aios_core.skill.run(id, inputs, ctx)`; agent-type skills
   need your reasoning wired as `context["agent_adapter"]` (or
   `task_executor` for planner cycles) — see SKILL_RUNTIME_SPEC.md §2.
3. To AUTHOR a skill: templates/skill/ + SKILL_AUTHOR_GUIDE.md; you are done
   when `validator … full` prints VALID and quality ≥85 — not when output
   "looks right."
4. Honor typed failures: NOT_EXECUTABLE means supply an adapter;
   OUTPUT_INVALID means YOUR output broke the schema — fix the output, never
   loosen the schema to pass (rule R10's spirit).

## Claude Opus
- **Reasoning depth**: high; sustains whole-milestone scope.
- **Implementation strategy**: author complete skills end-to-end
  (contracts→schemas→driver→tests in one session); take on MAJOR-version
  redesigns and cross-skill refactors.
- **Validation strategy**: run the full §V checklist + validator on every
  touched skill; you have the budget — use it.
- **Strengths**: contract design, decomposition (guide §2), catching
  cross-cutting violations. **Risk**: over-engineering — check LESSONS §2
  rejected-alternatives before proposing infrastructure.
- **Recommended tasks**: new skills from scratch; flagship-grade packages;
  legacy→full-profile migrations.

## Claude Sonnet
- **Reasoning depth**: focused; excels at bounded, well-specified units.
- **Implementation strategy**: one atomic unit per session — one driver, one
  contract file, one test suite; if it touches >4 files, split it.
- **Validation strategy**: validator on the one skill + the suites its tests
  belong to; full checklist at milestone exits only.
- **Strengths**: precise implementation against existing contracts;
  test-first loops. **Risk**: skipping memory updates — log.md +1 line is
  part of done.
- **Recommended tasks**: implement a driver against an Opus/human-written
  contract; add negative tests; fill template sections; fix validator FAILs.

## GPT (any capable GPT-class model)
- **Execution**: identical contracts; wire your client as
  `agent_adapter(manifest, inputs, context) -> dict matching output_schema` —
  schema rejection is correct behavior, not an integration bug.
- **Watch for**: Python 3.9 typing (R8); JSON-only manifests (R14); tests as
  standalone scripts, not pytest fixtures; cite file paths for every claim.
- **Recommended tasks**: start at Sonnet-profile scope until several
  validator-green cycles establish calibration, then widen.

## Gemini
- **Execution**: as GPT. Long-context strength tempts whole-repo rewrites —
  the charter forbids regeneration where refinement works; keep diffs
  minimal, one skill at a time.
- **Validation strategy**: if your tooling cannot execute local test
  scripts, you cannot mark work done (P6) — produce code + hand validation
  back explicitly.
- **Recommended tasks**: corpus/knowledge skills (M-K adjacent), example
  authoring, documentation-completeness passes — measurable, low blast
  radius, validator-checkable.

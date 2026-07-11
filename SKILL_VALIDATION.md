# SKILL VALIDATION — pipeline + quality score

Implementation: `aios_core/skill_sdk/` (validator.py, quality.py; entry
points re-exported in `aios_core/skill_sdk/validators/`).

**Location note:** the original deliverable path `/skill_runtime/validators/`
would have created a second runtime root, contradicting D14 ("the runtime is
reusable infrastructure and lives in aios_core/"). The validators are homed
at `aios_core/skill_sdk/validators/` instead — a deliberate, recorded
deviation, not an omission.

## CLI

```
python3 -m aios_core.skill_sdk.validator <skill_dir> [full|core]   # exit 0 = VALID
python3 -m aios_core.skill_sdk.quality  <skill_dir>                # JSON score
```

## The 9-stage pipeline (all deterministic, stdlib-only)

| stage | checks |
|---|---|
| V1 structure | required files/dirs per profile |
| V2 manifest | parses · 12 keys incl. purpose · id==folder · semver · runtime type · no unresolved __placeholders__ |
| V3 contracts | steps declared · steps appear in execution_contract.md · failure-handling section · memory_contract.md present when writes declared |
| V4 schemas | input/output schemas parse, type=object (file or inline) |
| V5 documentation | skill.md mandatory sections (7 in full profile) · CHANGELOG mentions current version |
| V6 examples | ≥1 example · ≥1 negative · all parse with `inputs` |
| V7 test execution | ≥1 test file · each exits 0 (run via subprocess) |
| V8 compatibility | python entrypoint imports + callable · driver source names no vendor (P8) · dependencies resolve in registry within constraints |
| V9 versioning | CHANGELOG top entry == manifest.version |

## Profiles

- **full** — required for every NEW skill (the canonical 11-file layout).
- **core** — manifest + skill.md + README only; exists to grade the pre-SDK
  library honestly instead of failing history. Legacy skills are migration
  debt: they pass core, score lower on quality, and migrate opportunistically
  (whenever a session next touches one, bring it to full profile — rule R16).

A useful property, verified: the unfilled template itself fails EXACTLY the
two placeholder checks (V2c id, V2f placeholders) and nothing else — the
validator proves a template is a template, and proves a filled one is done.

## Quality score (0–100, weighted, deterministic — no LLM judging, D10)

| category | weight | measured by |
|---|---|---|
| Completeness | 20 | fraction of canonical files present |
| Documentation | 15 | mandatory sections · no placeholders · real purpose |
| Testing | 15 | tests exist · pass · include a negative-path signal |
| Determinism | 10 | declared in skill.md · python driver, or agent w/ output schema |
| Memory safety | 10 | declared block · contract doc when writing · no bare wildcard |
| Portability | 10 | no vendor names in CODE/manifest (prose exempt — docs may cite models as examples of interchangeability) |
| Runtime compatibility | 10 | manifest registers · entrypoint/deps resolve |
| Maintainability | 10 | CHANGELOG discipline · semver · bounded file sizes |

## Current library baseline (measured 2026-07-06)

| skill | core-valid | quality |
|---|---|---|
| recursive_planner (flagship) | ✓ | ~74 |
| critic · evaluator · evidence_validation · hypothesis_generation · memory_compression | ✓ | ~59 |
| book_ingestion · concept_distillation · rag_search · retrieve_context | ✓ | ~53 |
| concept_map (pack) | ✗ (no README.md — real debt) | ~55 |

Common gaps: no per-skill tests/ (testing 0.0 — library skills are covered by
the shared suite, which the scorer intentionally does NOT credit: per-skill
tests are the SDK standard), missing contract files (completeness 0.27).
Interpretation: the score DISCRIMINATES (53–74 spread) — exactly what an eval
must do. New skills should score ≥85 (see SKILL_MARKETPLACE.md quality gate).

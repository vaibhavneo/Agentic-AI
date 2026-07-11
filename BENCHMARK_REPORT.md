# BENCHMARK REPORT — SDK self-test (Part 10)

**Question:** can a model with no conversation history recreate an existing
AIOS skill to production quality using only the SDK documentation?
**Method:** `concept_map` (Domain Pack skill) was treated as nonexistent. The
recreation used ONLY: its behavioral contract (`skill.md` + manifest schemas
— i.e., "the requirement"), `templates/skill/`, SKILL_SDK.md,
SKILL_AUTHOR_GUIDE.md, SKILL_RUNTIME_SPEC.md. The original **driver and any
test code were never read** during recreation.
**Artifact:** `aios_core/skill_sdk/benchmark/concept_map/` (full-profile
package; deliberately NOT registered — benchmark evidence, not a product
skill). Comparison is automated in `aios_core/tests/test_skill_sdk.py` so it
can never silently rot.

## Results (measured 2026-07-06)

| dimension | original (pack, pre-SDK) | recreation (SDK process) |
|---|---|---|
| **Behavior** | — | **set-equality 4/4 input cases** on the live store (node sets, edge multisets, counts all identical); ordering differs on 3/4 (see G1) |
| **Contracts** | manifest + skill.md only | full: manifest (12 keys) + skill.md + execution/memory/evaluation contracts |
| **Tests** | none in-package (covered indirectly by pack suite) | 12 checks: fixture ground truth, negative controls, live-store invariants at 3 floors, example replay — ALL PASS |
| **Documentation** | 55.4 quality; full-profile INVALID (missing README/tests/examples/contracts: V1a, V1b, V5a, V6a, V6b) | 100.0 quality; full-profile VALID 23/23 |
| **Compatibility** | dispatches through runtime ✓ | dispatches through runtime ✓ (same entrypoint pattern; V8 importable+vendor-clean) |

## Gap report

- **G1 — contract under-specification (found BY the benchmark, the most
  valuable result):** the original contract says "Deterministic" but never
  states node ORDERING. Original sorts by descending confidence; the
  recreation, reading only the docs, defensibly chose name-sort → 3/4 cases
  differ in order while being set-identical. **Root cause:** spec gap, not
  implementation error. **Fix path:** the SDK template already demands
  ordering be named in the Determinism section ("name any tolerated
  nondeterminism (timestamps, ordering)") — this gap is exactly why. The
  original's skill.md should gain one sentence; consumers must not depend on
  order until it does.
- **G2 — legacy packaging debt (expected, quantified):** the original is a
  core-profile skill (55.4/100; no in-package tests/examples/README). Not a
  behavior defect — its logic is fine — but the SDK process measurably
  produces a stronger artifact (100/100, 23/23) from the same requirement.
- **G3 — live-store examples can't freeze values:** the recreation's
  happy-path example asserts invariants rather than exact values because the
  underlying store drifts. Rule of thumb extracted: skills reading LIVE
  state should take a `store_path`-style test seam (the recreation added
  one; the original hardcodes the path — a minor testability gap in the
  original).

## Verdict

**The SDK passes its self-test.** A from-docs recreation achieved full
behavioral parity (set-level) and strictly higher packaging quality, and the
one divergence traced to a documented-missing sentence in the source
contract — which the SDK's own template already prevents for future skills.
Success criteria "design → implement → validate → document → version" were
all exercised end to end without conversation history.

# Changelog — teacher
<!-- Newest first. Every released version gets an entry. Semver per
SKILL_RUNTIME_SPEC.md: MAJOR = schema type/requiredness change, memory-contract
loosening, execution-step reorder/removal; MINOR = new optional input, extra
output field, new example/test; PATCH = docs/typo/test-only. -->

## 1.0.0 — 2026-07-10
- Initial release (WP-4 / M-P2a). Adaptive, source-grounded teacher skill:
  deterministic scope→retrieve→assess-mastery scaffolding + adapter-gated
  instruction, emitting explanation / source evidence / exercise / mastery
  check / recommended next action, plus an upsertable `concept_candidate`.
  Stateless; provenance and mastery adaptation are driver-owned. Replaces the
  legacy inline tutor path as the model-agnostic distillation/teaching seam.

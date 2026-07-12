# Changelog — mission_tasks
<!-- Newest first. Every released version gets an entry. Semver per
SKILL_RUNTIME_SPEC.md: MAJOR = schema type/requiredness change, memory-contract
loosening, execution-step reorder/removal; MINOR = new optional input, extra
output field, new example/test; PATCH = docs/typo/test-only. -->

## 1.0.0 — 2026-07-11
- Initial release (WP-3 / M-P1c). Create/set-done operations over plan.md's
  task lines, dispatcher-enforced (write-allowlist = plan.md only),
  idempotent by content (create) and by state (set_done). Powers
  `POST/PATCH /api/missions/{slug}/tasks` and the Execute-workspace Tasks tab
  + dashboard Today's Focus card.

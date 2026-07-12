# Changelog — central_orchestrator
<!-- Newest first. Semver per SKILL_RUNTIME_SPEC.md. -->

## 1.0.0 — 2026-07-11
- Initial release (WP-O5, Central Orchestrator Part 4). Deterministic
  scaffolding (roster load, choice validation, dispatch) + adapter-gated
  routing decision, mirroring teacher_driver.py's split. Falls back to
  brain_think on an unresolved app_id (H-O3). The one model-naming file is
  `orchestrator/fable_adapter.py` (Claude Fable 5), never this skill.

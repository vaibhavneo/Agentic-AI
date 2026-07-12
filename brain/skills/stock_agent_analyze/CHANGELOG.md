# Changelog — stock_agent_analyze
<!-- Newest first. Semver per SKILL_RUNTIME_SPEC.md. -->

## 1.0.0 — 2026-07-11
- Initial release (WP-O2, Central Orchestrator Part 4). HTTP wrapper around
  stock_agent/'s 7-agent pipeline (SSE `/api/analyze/stream`), chosen over
  in-process import because stock_agent/'s `agents/`/`tools/` packages
  collide with brain/'s own bare top-level names (D20).

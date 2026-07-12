# Changelog — vedic_astro_reading
<!-- Newest first. Semver per SKILL_RUNTIME_SPEC.md. -->

## 1.0.0 — 2026-07-11
- Initial release (WP-O2, Central Orchestrator Part 4). HTTP wrapper around
  vedic_astro/'s geocode->reading sequence (SSE `/api/reading/stream`),
  kept as one skill with driver-internal glue (H-O4). HTTP chosen over
  in-process import because vedic_astro/'s `agents/` package collides with
  brain/'s own bare top-level names (D20).

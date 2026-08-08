# Memory contract — healthpilot_log_coach_interaction v1.0.0

Mirrors manifest `memory` block (ENFORCED by the dispatcher).

- **root_param: "memory_root".** Caller-supplied directory, e.g.
  `healthpilot/data/aios_memory/` in a real deployment (gitignored, local-only
  — matches how `healthpilot/data/*.db` is already excluded from version
  control).
- **append_only: `conversations/*.md`.** The ONLY path shape this skill may
  create/modify. One file per profile (`conversations/<profile_id>.md`),
  each dispatch appends one line — never rewrites or deletes a prior line.
  A dispatch that tried to write anywhere else, or delete/replace existing
  content, would fail `VERIFY_MEMORY` with `MEMORY_VIOLATION`.
- **reads:** none — this skill never reads HealthPilot's own data back; it
  is a write-only audit sink.
- **content:** metadata only (timestamp, specialist, ai_used, tool NAMES) —
  never tool results, never the user's question or the Coach's answer text.
  This is a deliberate choice matching HealthPilot's own SAFETY.md: "No
  health data or medication details in logs by default."

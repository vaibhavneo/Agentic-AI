# Memory contract — central_orchestrator v1.0.0

Mirrors manifest `memory` block (ENFORCED by the dispatcher).

- **root_param: null (stateless).** No memory root; THIS skill's own
  dispatch produces zero `memory_changes` — verified by the runtime
  monitor's sha1 snapshot diff. (The DISPATCHED wrapper skill's own memory
  contract — all currently stateless too — governs whatever it does; this
  skill neither widens nor narrows that.)
- **reads:** `orchestrator/apps.json` (the app roster) — a repo config
  file, not a memory-root file, so it is outside the manifest's own
  `memory.read` declaration (same convention as skills reading
  `brain/skills/registry.json`).
- **writes:** none. All 5 apps are themselves stateless per-call; per D20's
  own reasoning, a routing "mission" would be a write-only mirror nobody
  reads — deliberately not built. `metrics.jsonl` (the runtime monitor's
  own unconditional audit trail) already records every routing decision.
- **immutable:** n/a.

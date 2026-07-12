# Memory contract — health_agent_analyze v1.0.0

Mirrors manifest `memory` block (ENFORCED by the dispatcher).

- **root_param: null (stateless).** No memory root; a dispatch produces zero
  `memory_changes` — verified by the runtime monitor's sha1 snapshot diff.
- **reads:** none. health-agent/'s own data (`health-agent/data/`, logs) is
  that app's own concern, outside AIOS's memory model.
- **writes:** none — this skill only reads health-agent/'s HTTP response.
- **immutable:** n/a.

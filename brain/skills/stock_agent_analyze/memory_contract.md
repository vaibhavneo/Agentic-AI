# Memory contract — stock_agent_analyze v1.0.0

Mirrors manifest `memory` block (ENFORCED by the dispatcher).

- **root_param: null (stateless).** No memory root; a dispatch produces zero
  `memory_changes` — verified by the runtime monitor's sha1 snapshot diff.
- **reads:** none. stock_agent/'s own tracking data (`stock_agent/data/`) is
  that app's own concern, outside AIOS's memory model — this skill neither
  reads nor declares it.
- **writes:** none — this skill only reads stock_agent/'s HTTP response; it
  never writes into stock_agent/'s own directory.
- **immutable:** n/a.

# Memory contract — vedic_astro_reading v1.0.0

Mirrors manifest `memory` block (ENFORCED by the dispatcher).

- **root_param: null (stateless).** No memory root; a dispatch produces zero
  `memory_changes` — verified by the runtime monitor's sha1 snapshot diff.
- **reads:** none. vedic_astro/'s own knowledge base
  (`vedic_astro/data/knowledge_base/`) is that app's own concern, outside
  AIOS's memory model.
- **writes:** none — this skill only reads vedic_astro/'s HTTP responses.
- **immutable:** n/a.

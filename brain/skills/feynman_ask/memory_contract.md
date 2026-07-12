# Memory contract — feynman_ask v1.0.0

Mirrors manifest `memory` block (ENFORCED by the dispatcher).

- **root_param: null (stateless from AIOS's point of view).** No memory
  root; a dispatch produces zero `memory_changes` — verified by the runtime
  monitor's sha1 snapshot diff.
- **reads:** none from a memory root. feynman_agent/'s own knowledge base
  (`feynman_agent/knowledge/`) is that app's own concern, outside AIOS's
  memory model.
- **writes:** none. feynman_agent/'s own per-session `history` list lives in
  an in-process dict inside feynman_agent/, not in any AIOS-governed file —
  it is process-lifetime state, not durable memory, and is explicitly out
  of this skill's scope.
- **immutable:** n/a.

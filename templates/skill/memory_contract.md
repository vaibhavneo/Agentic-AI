# Memory contract — __SKILL_ID__

Mirrors manifest `memory` block — that block is ENFORCED by the dispatcher
(writes outside `write ∪ append_only` fail the dispatch as MEMORY_VIOLATION);
this file explains intent.

- root_param: __null (stateless) | "memory_root"__
- reads: __what and why__
- writes: __what and why; state=overwrite, log/decisions=append-only__
- immutable: __what must never change and why__
- Compression: any file this skill appends to must stay within platform
  bounds (≤200 lines; log entries one line). __State how this skill complies.__

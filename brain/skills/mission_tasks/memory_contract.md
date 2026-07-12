# Memory contract — mission_tasks v1.0.0

Mirrors manifest `memory` block — that block is ENFORCED by the dispatcher
(writes outside `write ∪ append_only` fail the dispatch as MEMORY_VIOLATION);
this file explains intent.

- root_param: `"memory_root"` — the caller passes the MISSION's own directory
  (`memory/missions/<slug>/`). The dispatcher's before/after snapshot is
  taken ONLY under this path, so the enforcement below is scoped per-mission:
  a dispatch against mission A can never be credited (or blamed) for changes
  in mission B's directory.
- reads: `plan.md` — to locate/dedupe tasks. Nothing else is opened.
- writes: `plan.md` ONLY — and only when an operation is not a no-op
  (`changed:true`). This is the WP-3 invariant verbatim: the manifest's write
  allowlist is exactly `["plan.md"]`, nothing broader (no glob).
- append_only: none — `plan.md` here is edit-in-place (one line inserted or
  flipped), not append-only like `log.md`/`decisions.md`.
- immutable: none.
- Compression: this skill never grows `plan.md` unboundedly on its own — each
  `create` adds exactly one line, deduped against existing content, so a
  caller cannot balloon the file by retrying the same request. Enforcing the
  platform's overall 200-line-per-memory-file bound (memory_compression) is
  out of this skill's scope, same as every other skill that touches a single
  memory file.

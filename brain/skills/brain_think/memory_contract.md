# Memory contract — brain_think v1.0.0

Mirrors manifest `memory` block (ENFORCED by the dispatcher).

- **root_param: null (stateless).** No memory root; a dispatch produces zero
  `memory_changes` — verified by the runtime monitor's sha1 snapshot diff.
- **reads:** none. brain/'s own internal memory (`brain/data/memory/*.json`)
  is brain/'s concern, entirely outside this skill's manifest and outside
  AIOS's memory model — this skill neither reads nor declares it.
- **writes:** none.
- **immutable:** n/a.

Rationale: this skill is a pass-through call, not a durable-state owner. If
brain/'s internal memory ever needs to be inspected or governed from AIOS, that
is a separate, explicit skill/decision — not a side effect of this wrapper.

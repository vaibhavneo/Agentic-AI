# Memory contract — teacher v1.0.0

Mirrors manifest `memory` block (ENFORCED by the dispatcher: any write outside
`write ∪ append_only` fails the dispatch as `MEMORY_VIOLATION`).

- **root_param: null (stateless).** The skill takes no memory root and writes
  nothing. A dispatch produces zero `memory_changes` — verified by the runtime
  monitor's sha1 snapshot diff and asserted in tests.
- **reads:** none from a memory root. It reads the concept store via
  `second_brain.concept_store.load()` (read-only) to detect prerequisite gaps;
  callers may instead pass `mastery.prerequisites` to avoid even that read.
- **writes:** none. Deliberately: teaching produces a `concept_candidate` in
  its OUTPUT, and the teach→upsert→critic loop (M-P2a) is a DOWNSTREAM
  composition — `concept_store.upsert` + `evidence_validation` — owned by the
  caller/workflow, NOT by this skill. This keeps the write path in one
  audited place (D9: concepts.json is the source of truth; the skill never
  touches the rendered `knowledge_cache.md`).
- **immutable:** n/a (writes nothing).
- **Compression:** not applicable — no file is appended to. The `concept_candidate`
  the caller upserts is a single bounded record (name + one-sentence principle +
  one-sentence when_to_use + source list), never a transcript.

Rationale: statelessness makes the skill trivially safe to compose and re-run,
and forces every durable effect (concept upsert) through the approved memory
interfaces rather than a side effect hidden inside instruction generation.

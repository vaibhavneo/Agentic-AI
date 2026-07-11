# Execution contract — teacher v1.0.0

Executor-agnostic. Steps run in order; no step may be skipped or reordered
(reordering is a MAJOR version change). No step names a model — the only model
seam is Step 4's adapter call.

## Steps
1. **RESOLVE SCOPE** — pre: `topic` present. Determine retrieval scope from
   `mission_id` (mission's declared corpora) or explicit `corpora`. post:
   a non-empty scope exists, else `ValueError` (P9 — scope is never guessed).
2. **RETRIEVE EVIDENCE** — dispatch `retrieve_context` through the runtime
   (gateway path; no re-implemented retrieval). post: `source_evidence[]` =
   `{corpus, source, excerpt}` per hit, provenance intact. Failed retrieval ⇒
   `ValueError` (a lesson must be grounded).
3. **ASSESS MASTERY** — deterministic. Compute `prerequisite_gaps` (from
   `mastery.prerequisites`, else the concept graph's `depends-on` relationships
   with sub-floor confidence) and the `adaptation.level`
   (`introduce`/`reinforce`/`advance`) from `mastery.confidence`. Absent
   mastery ⇒ `introduce`, `mastery_known=false`; never claim mastery.
4. **INSTRUCT** — the ONLY generative step. Call `context["agent_adapter"]`
   with the topic, mode, adaptation, and retrieved evidence; it returns
   `{explanation, exercise, mastery_check, principle, when_to_use}`. No adapter
   ⇒ `NOT_EXECUTABLE`. Missing keys ⇒ `ValueError`.
5. **ASSEMBLE LESSON** — attach `source_evidence` and `concept_candidate.sources`
   from Step 2 (never from the adapter), compute `recommended_next_action` from
   the adaptation, and emit the lesson. post: conforms to `output_schema.json`.

## Failure handling (mandatory)
| condition | behavior | surfaced as |
|---|---|---|
| no `mission_id` and no `corpora` | raise ValueError "scope required (P9)" | EXECUTION_ERROR |
| retrieval dispatch not ok | raise ValueError with the underlying failure | EXECUTION_ERROR |
| `context["agent_adapter"]` absent | raise `executor.NotExecutable` | NOT_EXECUTABLE |
| adapter output missing required keys | raise ValueError naming the keys | EXECUTION_ERROR |
| adapter injects fabricated sources | ignored — provenance is driver-owned | (no effect) |

Retries: `execution.retries` = 0 (a generative miss is not masked by retrying;
the caller supplies a better adapter or input).

## Metrics
Every dispatch is recorded by the runtime monitor (elapsed_ms, ok, retries,
memory_changes — expected empty). Skill-specific signals worth watching:
`len(source_evidence)` (grounding breadth) and `adaptation.level` distribution.

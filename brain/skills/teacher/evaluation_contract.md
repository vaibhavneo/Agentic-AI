# Evaluation contract — teacher v1.0.0

Charter P6: build the eval FIRST; external ground truth beats self-consistency.
Every MUST is deterministic and implemented in `tests/test_skill.py` with a
fixed stub adapter (no model, no network) so grading never depends on an LLM.

## MUST checks (deterministic)
- **E1 — grounded provenance**: with a real corpus scope, every
  `source_evidence` entry carries a `{corpus, source}` from the retrieval
  gateway, and `concept_candidate.sources ⊆ {retrieved sources}`. Ground truth:
  the sources returned by `retrieve_context` for the query.
- **E2 — negative control (no scope)**: a call with neither `mission_id` nor
  `corpora` fails `EXECUTION_ERROR` — it never fabricates an ungrounded lesson.
- **E3 — adapter is the only model seam**: no adapter ⇒ `NOT_EXECUTABLE`; an
  adapter returning fabricated `sources` cannot change `source_evidence` or
  `concept_candidate.sources` (provenance is driver-owned).
- **E4 — mastery adaptation is honest**: `adaptation.level` is a pure function
  of `mastery` — absent/`null` confidence ⇒ `introduce` + `mastery_known=false`;
  a sub-floor prerequisite ⇒ `reinforce` with the gap named; high confidence,
  no gaps ⇒ `advance`. The skill never asserts the learner HAS mastered the
  topic (only `mastery_check` questions and a recommended next action).
- **E5 — output schema conformance**: the assembled lesson validates against
  `output_schema.json` (enforced by the runtime; asserted on the happy path).

## Quality checks (scored, optional)
- Q1 — explanation length within a sane band for `depth` (report, don't gate).
- Q2 — exercise `kind` matches `mode` where applicable (compare↔compare).

## Discrimination statement (mandatory)
Each MUST would catch a specific wrong implementation:
- E1 catches a build that lets the adapter supply `sources` (the classic
  hallucinated-citation bug).
- E2 catches defaulting to a corpus when scope is missing (a P9 violation).
- E3 catches making the skill runnable without a model (silent empty lessons)
  or trusting adapter-supplied provenance.
- E4 catches a "you have mastered X" deterministic claim, or an adaptation that
  ignores prerequisites.
- E5 catches a shape drift that a future UI would silently mis-render.

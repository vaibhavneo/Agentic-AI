# teacher — behavioral contract

## Purpose (mandatory)
Turn the platform's corpora into *learning*: a lesson that adapts to what the
learner already knows and cites where every claim comes from. A mission or the
Learning Agent reaches for this skill when a person needs to understand a
concept, not just receive an answer — and needs that understanding to be
verifiable (provenance) and resumable (structured output, no chat history).

## Business problem (mandatory)
Without it, "teaching" is a raw chatbot answer: unsourced, the same for a
novice and an expert, and impossible to verify or feed back into the concept
store. The manual alternative is a person re-reading the book and hand-writing
notes. This skill produces an adaptive, source-grounded, machine-checkable
lesson instead.

## Inputs (mandatory)
- `topic` (required, ≥3 chars): what to teach; also the retrieval query and the
  `concept_candidate` key unless `mastery.concept` overrides it.
- `mode`: instructional stance (`explain`/`socratic`/`exercise`/`compare`) — a
  hint to the adapter; it does NOT change the deterministic scaffolding.
- `depth`: requested explanation depth (adapter hint), orthogonal to the
  computed `adaptation.level`.
- `mission_id` **or** `corpora`: retrieval scope. Exactly one is required —
  scope is never guessed (P9). Absent both ⇒ `EXECUTION_ERROR`.
- `cross_corpus`, `top_k`: passed to the gateway.
- `mastery` (from the coach surface): `{concept, confidence 0-1|null,
  prior_activity, prerequisites[]}`. Absent ⇒ mastery unknown; instruction
  starts at `introduce` and NEVER claims the learner has mastered anything.

## Outputs (mandatory)
Five distinguished parts plus scaffolding: `explanation` (adapter-authored
text), `source_evidence[]` (`{corpus, source, excerpt}` — attached from the
gateway, not the adapter), `exercise` (`{prompt, kind}`), `mastery_check`
(`{question, expected_signal}` — a check, never a claim), and
`recommended_next_action` (`{action, trigger, evidence}`). Also `adaptation`
(deterministic level + rationale + `prerequisite_gaps[]`), a `concept_candidate`
(`{name, principle, when_to_use, sources}`, upsertable downstream), and
`provenance_grounded`. Invariant: `concept_candidate.sources` and every
`source_evidence.source` come from retrieval, never from the adapter.

## Determinism (mandatory)
**Agent-gated.** The `explanation`, `exercise`, `mastery_check`, and the
`principle`/`when_to_use` of the concept are produced by
`context["agent_adapter"]` (any model or human) and are non-deterministic. The
output schema enforces structure regardless of the adapter. Everything the
schema cannot enforce and that must be trustworthy — scope resolution, evidence
provenance, mastery adaptation level, prerequisite gaps, the recommended next
action — is computed DETERMINISTICALLY by the driver from inputs + the concept
store, so a weaker or adversarial adapter cannot forge provenance or overstate
mastery.

## Hidden-assumption audit (mandatory)
- Retrieval scope must resolve to at least one registered corpus — checked
  (missing scope or failed retrieval ⇒ `EXECUTION_ERROR`), not assumed.
- The concept graph is read via `second_brain.concept_store.load()`; when the
  store is absent or a concept is unknown, prerequisite detection degrades to
  "no gaps found" rather than erroring, and callers may pass
  `mastery.prerequisites` explicitly to override.
- No filesystem writes and no reliance on cwd or environment: the skill is
  stateless (see memory_contract.md).
- No reliance on conversation history: all learner state arrives via `mastery`.

## Preconditions / Postconditions (mandatory)
- Pre: `context["agent_adapter"]` is a callable; a corpus scope is supplied;
  the `retrieve_context` dependency is registered.
- Post: output validates against `output_schema.json`; `source_evidence` and
  `concept_candidate.sources` derive only from retrieved chunks; no memory
  files changed (verified by the dispatcher's memory diff).

## When NOT to use (optional but recommended)
To distill an already-read set of chunks into a stored mental model without the
instructional wrapper, use `concept_distillation`. To only fetch cited chunks,
use `retrieve_context`. To score a concept's evidence, use `evidence_validation`.

# feynman_ask — behavioral contract

## Purpose (mandatory)
Give the Central Orchestrator one typed, dispatcher-enforced way to hand a
physics question to feynman_agent/'s existing Feynman-technique QM tutor,
without reaching into its internals or its per-session history directly.

## Business problem (mandatory)
Without this skill, dispatching to feynman_agent/ means importing
`get_session` directly and managing sys.path scoping, session ids, and
result shape by hand at every call site. This skill makes that one call
typed, metered, and swappable.

## Inputs (mandatory)
- `question` (required): the physics question, passed to the tutor verbatim.
- `session_id` (optional, default `"default"`): feynman_agent/'s own
  multi-turn conversation key (last 10 turns kept for follow-ups).

## Outputs (mandatory)
- `app`: always `"feynman_agent"`.
- `answer`: the tutor's answer string, unmodified.
- `sources`: book sources the tutor's own retrieval cited, unmodified.
- `chunks_retrieved`: how many knowledge-base chunks were retrieved.

## Determinism (mandatory)
**Not deterministic** — feynman_agent/ makes its own model call internally
(via its own `_call_llm`). This skill's own logic (session resolution, result
wrapping) is fully mechanical; it has no adapter seam of its own and names
no model.

## Hidden-assumption audit (mandatory)
- Assumes `feynman_agent/` is importable once `feynman_agent/` itself (not
  the repo root) is on `sys.path` — same scoping convention as every other
  in-process driver.
- feynman_agent/'s knowledge base is lazily ingested on first call in a
  process (one-time cost, documented in the app's own README) — this skill
  does not pre-warm it.
- Session state (`history`) lives in feynman_agent/'s own in-process
  dictionary, keyed by `session_id` — it is NOT durable across process
  restarts; this skill does not add persistence.

## Preconditions / Postconditions (mandatory)
- Pre: `question` is a non-empty string.
- Post: output validates against `output_schema.json`; no memory files
  changed (stateless from AIOS's point of view).

## When NOT to use (optional but recommended)
For general-purpose or non-physics tasks, use `brain_think` (or let
`central_orchestrator` route automatically).

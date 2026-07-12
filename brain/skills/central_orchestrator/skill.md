# central_orchestrator — behavioral contract

## Purpose (mandatory)
Give a person (or another system) one entry point for 5 independently-built
AI applications: hand it a free-text task, and it picks the right app and
dispatches to it — without the caller needing to already know which of the
5 apps answers which kind of question.

## Business problem (mandatory)
Without this skill, using brain/, feynman_agent/, stock_agent/,
health_agent/, or vedic_astro/ requires knowing all 5 exist and picking the
right one by hand every time. A raw LLM router without a validated roster
risks dispatching to a nonexistent or hallucinated app id. This skill makes
the routing decision typed, auditable (every dispatch recorded by the
runtime monitor), and safe against a wrong or adversarial routing answer.

## Inputs (mandatory)
- `task` (required): the free-text task. Doubles as the literal input to
  `brain_think`/`feynman_ask` if one of those is chosen.
- `app_inputs` (optional): structured inputs for the target app — REQUIRED
  if routing resolves to `stock_agent_analyze`, `health_agent_analyze`, or
  `vedic_astro_reading` (their inputs — a ticker, a vitals string, birth
  data — cannot be inferred from free text by this skill; forcing that
  inference would be a second undisclosed generative step this skill
  deliberately does not add).

## Outputs (mandatory)
- `app_chosen`: the adapter's app_id, ONLY if it resolved to a real roster
  entry — `null` whenever `fallback_used` is true.
- `skill_dispatched`: the skill_id actually run.
- `fallback_used`: true iff the adapter's choice didn't resolve and
  `brain_think` was used instead (H-O3).
- `reasoning`: the adapter's one-sentence explanation.
- `result`: the dispatched wrapper skill's own output, unchanged.

## Determinism (mandatory)
**Adapter-gated for the routing DECISION only.** `context["agent_adapter"]`
(any model or human) chooses which app_id best fits the task; everything
else — loading the roster, validating that choice against the real known
app ids, falling back on a miss, dispatching the resulting skill through
the runtime — is computed DETERMINISTICALLY by the driver, so a weak or
adversarial adapter cannot make this skill dispatch to a skill that doesn't
exist.

## Hidden-assumption audit (mandatory)
- The roster is read from `orchestrator/apps.json` (H-O6: config file, not
  code) — adding a 6th app means adding one entry there plus its own
  wrapper skill, never touching this skill's code.
- The adapter's answer is data, never an instruction: an `app_id` outside
  the roster (including a hallucinated one) is treated identically to a
  `null` answer — both fall back to `brain_think`.
- `stock_agent_analyze` / `health_agent_analyze` / `vedic_astro_reading`
  need structured `app_inputs`; a caller that routes to one of them without
  supplying `app_inputs` gets a typed `EXECUTION_ERROR`, not a guessed or
  empty dispatch.

## Preconditions / Postconditions (mandatory)
- Pre: `context["agent_adapter"]` is a callable; `task` is a non-empty
  string; `orchestrator/apps.json` exists and parses.
- Post: output validates against `output_schema.json`; the dispatched
  skill's own memory contract governs any memory writes (this skill itself
  writes nothing); no memory files changed by this skill directly.

## When NOT to use (optional but recommended)
If you already know which app should handle the task, dispatch its wrapper
skill directly (`brain_think`, `feynman_ask`, `stock_agent_analyze`,
`health_agent_analyze`, `vedic_astro_reading`) — skipping the routing
decision entirely.

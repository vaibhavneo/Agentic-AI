# Execution contract — central_orchestrator v1.0.0

Executor-agnostic. Steps run in order. No step names a model — the only
model seam is Step 2's adapter call.

## Steps
1. **LOAD APP ROSTER** — pre: none. Read `orchestrator/apps.json` (app_id ->
   `{description, skill_id, invocation, ...}`). A test may inject
   `context["_apps_roster"]` to stay hermetic. post: a non-empty roster dict.
2. **CLASSIFY** — the ONLY generative step. Call `context["agent_adapter"]`
   with `{task, apps: roster}`; it returns `{app_id, reasoning}`. No adapter
   ⇒ `NOT_EXECUTABLE`.
3. **VALIDATE CHOICE** — deterministic, driver-owned (mirrors
   `RouterAgent._classify`'s own defensive pattern,
   `brain/agents/specialist_agents.py:242-258`). If `app_id` is a key in
   the roster, use its `skill_id`; otherwise (missing, null, or unknown —
   including a hallucinated id) fall back to `brain_think` and set
   `fallback_used=true`, `app_chosen=null` (H-O3). The adapter's answer is
   never trusted blindly.
4. **DISPATCH** — map `task`/`app_inputs` onto the target skill's own input
   shape (`brain_think`/`feynman_ask` take the bare `task`; the other three
   require `app_inputs`, else `ValueError`) and dispatch it through
   `aios_core.skill.run`. A dispatch failure raises `ValueError` naming the
   underlying skill's failure. post: `{task, app_chosen, skill_dispatched,
   fallback_used, reasoning, result}` conforms to `output_schema.json`.

## Failure handling (mandatory)
| condition | behavior | surfaced as |
|---|---|---|
| `task` missing/empty | schema validation rejects before dispatch | INPUT_INVALID |
| `context["agent_adapter"]` absent | raise `executor.NotExecutable` | NOT_EXECUTABLE |
| adapter returns unparseable/malformed output | driver treats as no valid app_id -> fallback (never raises) | (no effect — see Step 3) |
| adapter's `app_id` not in roster | fallback to `brain_think`, `app_chosen=null` | (no effect — by design, H-O3) |
| target skill requires `app_inputs` but none supplied | raise `ValueError` | EXECUTION_ERROR |
| dispatched skill itself fails | raise `ValueError` naming its failure | EXECUTION_ERROR |

Retries: `execution.retries` = 0 (a routing miss is masked by the fallback,
not by retrying the same ambiguous task against the same adapter).

## Metrics
Runtime monitor records elapsed_ms/ok/memory_changes (expected empty) for
this dispatch; the DISPATCHED skill's own dispatch is separately recorded
(two rows in `metrics.jsonl` per call — the routing decision and the actual
work). Skill-specific signal worth watching: `fallback_used` rate (a high
rate may indicate the roster's descriptions need improving, or a 6th app is
missing).

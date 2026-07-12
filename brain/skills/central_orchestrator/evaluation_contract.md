# Evaluation contract — central_orchestrator v1.0.0

Every MUST is deterministic and implemented in `tests/test_skill.py` with a
fixed stub adapter + a fixed stub roster (`context["_apps_roster"]`) — no
model, no network.

## MUST checks (deterministic)
- **E1 — valid routing dispatches the chosen app**: a stub adapter
  returning a real roster `app_id` dispatches that app's own skill (proven
  with a stubbed downstream skill), with `app_chosen` set and
  `fallback_used=false`.
- **E2 — negative control (no adapter)**: no `context["agent_adapter"]` ⇒
  `NOT_EXECUTABLE`, never a silent default route.
- **E3 — unknown/hallucinated app_id falls back, never dispatches blindly**:
  a stub adapter returning an `app_id` NOT in the roster (or `null`, or
  malformed JSON) results in `fallback_used=true`, `app_chosen=null`,
  `skill_dispatched="brain_think"` — the adapter's answer is data, never an
  instruction (H-O3).
- **E4 — structured-input apps require app_inputs**: routing to
  `stock_agent_analyze`/`health_agent_analyze`/`vedic_astro_reading`
  without `app_inputs` supplied fails `EXECUTION_ERROR`, never a guessed or
  empty dispatch.

## Discrimination statement (mandatory)
- E1 catches a build that ignores the adapter's choice entirely (always
  routing to one app).
- E2 catches a build that has a silent default adapter (masking the
  requirement that SOME reasoning source must be supplied).
- E3 catches the single most important bug class for this skill: trusting
  an LLM's raw routing answer without validating it against reality —
  exactly the defensive check `RouterAgent._classify` already proves out
  elsewhere in this codebase.
- E4 catches a build that silently infers a ticker/vitals/birth-data from
  free text via an undisclosed second model call, hiding a real generative
  step from the caller.

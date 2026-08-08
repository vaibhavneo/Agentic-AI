# Execution contract — healthpilot_health_pattern_analyst v1.0.0

**Runtime: agent.** No python entrypoint — the caller MUST supply
`context["agent_adapter"]`, e.g.
`aios_core.runtime.drivers.healthpilot_specialist_adapter.make_adapter()`,
which POSTs to HealthPilot's own `/api/profiles/<id>/coach/ask` (D20: HTTP,
never a direct import of HealthPilot's `agents/` package — see that
adapter's own docstring for why).

Steps:
1. **ROUTE TO SPECIALIST** — the adapter maps this skill's id
   (`healthpilot_health_pattern_analyst`) to HealthPilot's own internal specialist key
   (`health_pattern_analyst`, from `agents/specialists.py::SPECIALISTS`) and sends
   it as `specialist` in the request body, bypassing HealthPilot's own
   keyword router (`agents/router.py`) for this ONE call only — the router
   itself is untouched and still runs for the live Coach UI's own requests,
   which never send this override.
2. **RUN TOOL-CALLING LOOP** — happens entirely inside HealthPilot's own
   process, using its EXISTING orchestrator + tool_registry code, unmodified
   by this retrofit except for the additive `specialist_override` /
   `model_override` parameters on `answer_question`, both defaulting to
   `None` (byte-identical behavior when omitted).
3. **RETURN ANSWER + DATA USED** — HealthPilot's response is returned as-is;
   this skill never edits `answer` or `data_used`.

No adapter supplied in `context` -> `NOT_EXECUTABLE` (never silently falls
through to a different execution path — see aios_core/runtime/executor.py).

This skill answers as the **Health Pattern Analyst** specialist specifically.

# Execution contract — healthpilot_log_coach_interaction v1.0.0

**Runtime: python.** Entrypoint:
`aios_core.runtime.drivers.healthpilot_log_coach_interaction_driver:run`.
Pure stdlib (`datetime`, `pathlib`) — no HealthPilot imports, no network,
fully deterministic.

Steps:
1. **BUILD RECORD** — one line: ISO-8601 UTC timestamp, `specialist`,
   `ai_used`, and the joined `tool_names` (or `(none)` if empty).
2. **APPEND FILE** — creates `conversations/` under `memory_root` if
   missing, appends the line to `conversations/<profile_id>.md`.

Not wired into HealthPilot's live Coach call path in this PoC retrofit —
see the retrofit PR description's "known limitations" section. It is fully
functional and dispatchable on its own (proven by
`healthpilot/tests/integration/test_aios_core_retrofit.py`), but
`agents/orchestrator.py::answer_question` does not yet call it
automatically, since HealthPilot must keep working standalone (outside this
monorepo, where `aios_core` doesn't exist) and this PoC didn't add the
import-guard that would require.

# Architecture

```
Browser (server-rendered Jinja2 + vanilla JS)
        │
        ▼
Flask app (web/app.py) ── one factory, one blueprint-free routes file
        │
        ▼
Domain services (app/, nutrition/, vitals/, exercise/, meal_planning/, insights/)
   - each does real validation + arithmetic + SQL, no LLM involvement
        │
        ▼
safety/ — deterministic thresholds, gates, and the BP safety engine
   - imported BY domain services, not a separate layer requests pass through
        │
        ▼
database/db.py — SQLite connection + migration runner
```

```
AI path (only reachable through agents/orchestrator.py):

  user message → agents/router.py (keyword routing, no LLM call)
               → agents/specialists.py (system prompt + tool allowlist for the chosen specialist)
               → DeepSeek/OpenAI-compatible tool-calling loop (agents/orchestrator.py)
                     ↕ tool calls
               → agents/tool_registry.py → tools/*.py → same domain services as the REST API
               → final answer + "data used" (every tool call + its real result)
```

## Why this shape

**The LLM is never on the critical path for a number.** Every quantity shown anywhere in the app — nutrition totals, BP category, targets, correlations, health-score components — is computed by plain Python in a domain service and persisted or derived from SQLite. The LLM's only two jobs are (1) turning free text into *candidate* structures for deterministic code to resolve (`nutrition/nl_logging.py`, meal-plan template selection) and (2) turning already-computed results into prose for the Coach. Neither job lets it invent a number, decide a safety threshold, or write data on its own — see [SAFETY.md](SAFETY.md) for the enforcement mechanism, not just the intent.

**Read tools vs. write tools.** `agents/tool_registry.py` — the only surface the chat agentic loop can reach — exposes exclusively read-only tools (`get_*`, `calculate_*`, `search_food`, `analyze_health_patterns`, `generate_daily_plan` which doesn't persist). Nothing that writes a BP reading, meal, workout, or plan is reachable from freeform chat. Data entry happens through dedicated UI forms (Profile, Meals, Vitals, Activity, Weekly Plan), each backed by the same deterministic validation the API and CSV import use. This was a deliberate scope decision: an agent silently writing a BP reading (which can trigger an emergency safety event) from a misread chat message is a risk not worth taking for the UX gain.

**profile_id is never taken from model output.** `agents/tool_registry.execute_tool` strips any `profile_id` a tool call's arguments might contain and always injects the session's authenticated profile_id. This is what keeps multi-profile isolation intact even when an LLM is technically capable of hallucinating or being prompted to request another profile's id (tested in `tests/unit/test_tool_registry.py::test_execute_tool_strips_model_supplied_profile_id`).

**Graceful AI degradation, not AI-required.** Every AI-touched feature has a deterministic fallback:
- NL food logging (`nutrition/nl_logging.py`): AI-parsed candidates when configured; a comma/"and" heuristic splitter otherwise.
- AI Coach (`agents/fallback_coach.py`): keyword-routed direct tool calls with a templated real-data answer when no provider is configured or the AI call fails outright.
- Meal planning (`meal_planning/daily_planner.py`): fully deterministic template + arithmetic engine; no AI call in the critical path at all today (see "Known limitations" in HANDOFF.md for where an LLM could add value later — smarter substitution, not the validation itself).

Every AI call path is wrapped so a network failure or bad response degrades to the deterministic fallback rather than 500ing (`agents/orchestrator.py::answer_question`'s try/except).

## Module map

| Path | Responsibility |
|---|---|
| `app/` | Config, Profile, Medication, shared input validation, CSV import, data export |
| `database/` | SQLite connection + migration runner (`migrations/*.sql`, applied in filename order, tracked in `schema_migrations`) |
| `safety/` | Thresholds/constants, BP safety engine, potassium/protein safety gates, audit log |
| `nutrition/` | Food/Serving/Meal models, provider interface (USDA + manual), NL logging pipeline, target computation |
| `vitals/` | BP/weight/sleep/other-vitals recording, history, averages, trends |
| `exercise/` | Cardio + strength workout logging, weekly rollups |
| `meal_planning/` | Deterministic daily/weekly plan generation + validation/repair, grocery list |
| `insights/` | Cross-domain pattern analysis, health-score components, today's-insight picker, weekly summary |
| `agents/` | LLM client wrapper, tool registry/specs, specialist definitions, router, orchestrator, no-AI fallback |
| `tools/` | Thin JSON-in/JSON-out wrappers over domain services — the functions agents actually call |
| `web/` | Flask app factory + routes, Jinja templates, static JS/CSS |
| `tests/` | `unit/`, `integration/`, `security/` |

## Request lifecycle (a typical write, e.g. record_bp)

1. `web/app.py` route parses the request, resolves `profile_id` from the session (never trusts a client-supplied one for anything but explicit `/api/profiles/<id>/...` REST calls, which Flask's routing itself scopes).
2. Calls into `vitals/bp_service.py`, which validates input ranges (`safety/constants.py`), calls the pure `safety/bp_safety.py::evaluate_bp_reading`, persists the reading with parameterized SQL, and logs a `safety_events` row if warranted.
3. Returns a plain dict; the route wraps it in `jsonify`.

No layer in this path calls an LLM. The AI Coach can *read* the result afterward through `get_bp_history`/`calculate_bp_trend`, but never writes it.

## Multi-profile isolation

Every profile-owned table has a `profile_id TEXT REFERENCES profiles(id) ON DELETE CASCADE` column, and every service function takes `profile_id` explicitly and filters every query by it — there is no implicit "current user" state on the server beyond the Flask session's `active_profile_id`, and even that is only used to pick which profile_id a page passes into its API calls. `tests/security/test_full_isolation.py` verifies zero cross-profile leakage and zero orphaned rows after a cascade delete, across every table in the schema.

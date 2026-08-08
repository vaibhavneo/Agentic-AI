# Testing

```bash
source .venv/bin/activate
python -m pytest tests/ -q
```

**322 tests, all passing** as of this writing (32 unit files, 9 integration files, 5 security files — parametrized cases push the actual run count above the file/`def test_` count).

## Layout

- `tests/unit/` — one file per domain service/module, isolated database per test (`tests/conftest.py`'s `isolated_db` fixture: fresh SQLite file in a tmp dir, migrations applied, connection torn down after).
- `tests/integration/` — exercises the Flask API/pages end-to-end via `app.test_client()`.
- `tests/security/` — multi-profile isolation, cascade-delete completeness, SQL-injection resistance, secrets-in-logs static checks, CSV/export input safety.

No test hits a real network — the USDA provider and DeepSeek/Anthropic clients are either unconfigured (falls back to deterministic paths) or mocked (`tests/unit/test_orchestrator.py` stubs the OpenAI-SDK response shape by hand, no `unittest.mock.patch`-of-requests needed since nothing real is called).

## What's covered, by area

**Nutrition arithmetic** — `test_meal_service.py`, `test_daily_service.py`: meal/daily totals hand-verified against known seed-food values (e.g. banana at 89kcal/100g × grams/100).

**Sodium limits / protein-target handling / potassium safety** — `test_safety.py` (potassium classifier + supplement gate), `test_targets.py` (protein gate blocking a very-active profile with unknown kidney status, clinician override), `test_daily_planner.py` (a generated plan's sodium never exceeds the target beyond tolerance, even after the repair loop).

**BP averaging/trends/safety thresholds** — `test_bp_safety.py` is the most exhaustive file in the suite: every category boundary (119/120, 129/130, etc.), the "more severe of the two numbers" rule, the crisis+symptom emergency escalation, a parametrized grep across every category/symptom combination for forbidden acute-treatment words, and the diastolic-≥-systolic validation bug found during the M3 self-review. `test_bp_service.py` covers average/trend arithmetic and the safety_events audit trail.

**Exercise summaries** — `test_activity_service.py`: weekly rollup math (moderate vs. vigorous minutes kept separate, CDC-style weighted total), wearable-calorie conservative discount (never 1:1).

**Meal replacement / weekly-plan constraints** — `test_weekly_planner.py`: swap only touches the target meal (every other day's totals asserted byte-identical before/after), a locked meal can't be swapped, `test_swap_meal_actually_changes_the_food_selection` (regression test for a real bug found during the M8 walkthrough — swap was deterministically regenerating the identical meal).

**Grocery aggregation** — `test_grocery.py`: sums grams for the same food across multiple meals in a week, category mapping.

**Multi-profile isolation** — `tests/security/test_full_isolation.py`: two fully-populated profiles (medication+log, meal, water, BP, weight, sleep, other-vitals, workout, weekly plan) asserted to share zero rows across every profile-owned table, then a cascade-delete asserted to leave zero orphans anywhere (including transitively-cascaded child tables: meal_foods, strength_sets, plan_days) while leaving the other profile untouched.

**CSV import + invalid-input rejection** — `test_csv_import.py`: each importer's template imports cleanly; malformed/impossible rows (systolic 500, diastolic>systolic, unknown symptom, non-numeric weight, cardio without intensity) are rejected individually while valid rows in the same file still import; empty file raises.

**Medication safety behavior** — `test_medication.py`: ARB/ACE-inhibitor/potassium-sparing-diuretic name substrings auto-flag `potassium_risk`; manual override; updating a name recomputes the auto flag.

**Agent tool execution** — `test_tool_registry.py`, `test_orchestrator.py`: every specialist's declared tools actually exist in the registry; a model-supplied `profile_id` is always overridden by the session's; a tool call outside a specialist's allowlist is rejected; the tool-call loop terminates at `MAX_TOOL_ITERATIONS` rather than looping forever; an AI-call exception falls back gracefully instead of 500ing.

**No hallucinated nutrition data** — `test_food_service.py::test_search_no_match_returns_empty_not_fabricated`; `test_nl_logging.py::test_log_food_from_text_never_invents_nutrition_for_unresolved` (an unresolved NL candidate is reported, never guessed).

**Pattern-analysis minimum sample sizes** — `test_pattern_engine.py`: below `MIN_SAMPLE_SIZE` reports `insufficient_data` (never a fabricated correlation); a zero-variance series reports `no_variation`; a strongly-constructed correlation is computed correctly (r > 0.9) with the causation caveat attached.

## Browser acceptance walkthrough

**No Playwright/Selenium/Chromium was available in this build environment.** The full spec'd walkthrough (create profile → set targets → record medication → log morning BP → log breakfast via NL → verify totals → log a walk + strength session → generate remaining meals → confirm they fit remaining sodium/protein → generate weekly plan → replace one dinner → confirm only that day's totals change → view grocery list → add historical BP readings → verify trend → ask AI Coach about the trend → confirm it cites real data) was run against the live dev server via direct HTTP requests hitting the exact same routes the browser's JS would call, with results inspected at each step. Every step passed, including two real bugs found and fixed *during* the walkthrough (see HANDOFF.md).

**What this verified:** every route/endpoint returns correct data and status codes; the safety engine behaves correctly end-to-end; templates render without Jinja errors for every page in the nav; zero exceptions in the Flask server log across the full sequence.

**What this did NOT verify** (the honest gap): actual JavaScript execution in a browser DOM, browser console errors, visual rendering/CSS layout, cross-browser/mobile behavior, or real click-driven form interaction (the equivalent `fetch()` calls the JS would issue were tested directly, not the event-listener/DOM code in `web/static/*.js` itself). Recommended next step: run the same sequence through Playwright once available, targeting the actual UI controls rather than their underlying API calls.

## Known test-writing gotcha (for future contributors)

Jinja2 resolves `x.items` to the dict method `dict.items` (bound, uncalled) rather than the `"items"` key when `x` is a plain dict — this caused a real bug in two templates (`meals.html`, `weekly_plan.html`) found via a 500 in `test_weekly_plan_page_shows_plan_when_exists`. Use `x['items']` bracket notation for that specific key name in templates.

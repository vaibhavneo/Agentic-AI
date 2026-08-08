# Handoff

## Status

All 8 milestones complete. 322 automated tests passing. Full manual walkthrough passed against the live server (see TESTING.md for exactly what was and wasn't verified — no real browser automation was available in this environment).

## Startup

```bash
source .venv/bin/activate
cp .env.example .env   # fill in DEEPSEEK_API_KEY, optional
python run.py
```
→ http://127.0.0.1:3000

## What's real vs. what's scoped out

Everything described in the build prompt is implemented with real logic behind it — no decorative dashboard cards, no prompt-only agents. Two deliberate scope decisions worth knowing about:

1. **The AI Coach chat can't write data.** It can call `get_*`/`calculate_*`/`search_food`/`analyze_health_patterns`/`generate_daily_plan` (none of which persist) but nothing that logs a BP reading, meal, workout, or plan. See ARCHITECTURE.md's "Why this shape" section for the reasoning — the short version is that an agent silently writing a BP reading from a misread chat message isn't a risk worth taking for the UX gain, and every write path already has a dedicated, fully-validated UI form.

2. **Plan adherence (Health Score component) is a proxy, not a verified match.** There's no link today between a specific `plan_meals` row and the `meals` row that fulfilled it — so "plan adherence" measures logging consistency (days with ≥1 meal logged / 7) rather than "did you actually eat what was planned." This is stated explicitly in the UI (`insights/health_score.py::_plan_adherence`'s inputs include a `note` field) rather than silently overclaiming.

## Bugs found and fixed during the build (self-review pattern)

The milestone checkpoints (M1, M3) and the M8 walkthrough surfaced real issues — listed here so the pattern of "review catches things" is visible, not just claimed:

- **M3 checkpoint**: `record_bp` didn't check diastolic ≥ systolic (physiologically impossible), so an 80/120 reading was silently accepted and misclassified. Fixed with 3 regression tests.
- **M8, building the CSV-import security test**: discovered `reading_date`/`log_date`/`workout_date`/`meal_date` parameters across BP, weight, sleep, other-vitals, exercise, and meal services accepted **any string** with zero format validation — a malformed date would silently corrupt chronological queries. Added `app/validation.py::validate_date_str` and wired it into all six call sites, plus a fix for the same gap in `meal_planning/weekly_planner.py::_week_start` and the `/weekly-plan` page route (both called `dt.date.fromisoformat` directly on user input, which would 500 on garbage input — now redirects/400s cleanly).
- **M8 walkthrough, step "replace one dinner"**: `swap_meal` was regenerating the *exact same* meal every time — the template-selection loop always restarted from attempt 0, so "swap" was a silent no-op. Fixed by tracking which template variant produced the current foods and starting the next search one variant past it (`meal_planning/weekly_planner.py::_current_template_attempt`). Regression test: `test_swap_meal_actually_changes_the_food_selection`.
- **M8, writing templates**: `weekly_plan.html` and `meals.html` both had `{% for item in meal.items %}`, which Jinja2 resolves to the dict's `.items()` *method* (not the `"items"` key) — a `TypeError` that only manifested once a template actually had `items` in it (undetected by earlier tests because they never populated that path). Fixed with bracket notation; see TESTING.md's "known gotcha" section.

## Startup command (repeated for convenience)

```bash
python run.py
```

## Recommended next milestone

Nothing from the original spec is outstanding, but if continuing:

1. **Link plan meals to logged meals** so "plan adherence" becomes a real match instead of a proxy, and so "mark this planned meal as eaten" can one-click-log it via the existing `nutrition/meal_service.py` path.
2. **Wearable/device integrations** (Apple Health, Google Fit, Fitbit, Garmin, smart BP monitors) — the adapter interface point is `nutrition/providers/base.py`'s pattern, which should be mirrored for vitals/exercise sources; CSV import already covers the manual-entry half of this requirement.
3. **Raise `insights/pattern_engine.py::MIN_SAMPLE_SIZE`** from 5 to something like 10-14 before any real-user deployment — flagged in SAFETY.md as a known, deliberate-for-now gap.
4. **Real browser test pass** with Playwright once available, targeting actual UI controls (clicks, form fills) rather than the equivalent API calls — see TESTING.md for exactly what the HTTP-level walkthrough did and didn't cover.
5. **DeepSeek tool-calling loop for the Anthropic fallback provider** — currently, if only `ANTHROPIC_API_KEY` is set (no DeepSeek key), the Coach uses the no-AI deterministic fallback rather than a real Claude tool-calling loop (`agents/orchestrator.py`'s `else` branch). Not needed for the DeepSeek-primary setup this build targeted, but worth closing if Anthropic becomes a first-class path.

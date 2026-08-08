# HealthPilot AI

A local-first personal health-management copilot: nutrition, blood pressure, and fitness tracking with AI-assisted planning and coaching. **This is not a diagnostic system** — see [SAFETY.md](SAFETY.md) for what it will and will never do.

## Install

Requires Python 3.9+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `DEEPSEEK_API_KEY` (free key at https://platform.deepseek.com). Everything works without it — nutrition logging falls back to a heuristic text parser and the AI Coach falls back to direct data lookups — but conversational answers and richer natural-language food logging need a configured provider.

## Startup

```bash
source .venv/bin/activate
python run.py
```

Serves on **http://127.0.0.1:3000** (override with `HEALTHPILOT_PORT` in `.env`). On first run it initializes `data/healthpilot.db` (SQLite) and applies all migrations automatically.

## Configuration

All config lives in `.env` (gitignored) — see `.env.example` for the full list:

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | Enables the AI Coach's conversational tool-calling loop and richer NL food-logging parsing. OpenAI-compatible; `DEEPSEEK_MODEL` defaults to `deepseek-v4-flash`. |
| `ANTHROPIC_API_KEY` | Fallback provider if DeepSeek isn't configured (limited: no tool-calling loop, falls back to direct data lookups like the no-key path). |
| `USDA_FDC_API_KEY` | Optional. Enables live USDA FoodData Central lookups on top of the built-in 33-item seed food database. Free at https://fdc.nal.usda.gov/api-key-signup.html. |
| `HEALTHPILOT_PORT` | Local server port, default 3000. |
| `HEALTHPILOT_DB_PATH` | SQLite file path, default `data/healthpilot.db`. |
| `HEALTHPILOT_SECRET_KEY` | Flask session signing key. Change it if this ever runs beyond local single-user use. |

## Food data

Nutrition lookups go through a provider interface (`nutrition/providers/base.py`) so sources can be swapped or added:

- **Seed/manual data** (`nutrition/food_service.py`, seeded in `migrations/003_nutrition_seed_foods.sql`): ~33 common foods with standard, commonly-published per-100g nutrition facts. Works with zero configuration.
- **USDA FoodData Central** (`nutrition/providers/usda.py`): optional, live search, results cached locally on first use.
- **Manual label entry**: users can type in numbers straight off a nutrition label (`create_manual_food`) for anything not found.

Nutrition values are never invented by the LLM — see [SAFETY.md](SAFETY.md).

## Storage & backups

Everything lives in one SQLite file (`data/healthpilot.db` by default). To back up: copy that file while the app isn't writing to it (or use `sqlite3 data/healthpilot.db ".backup backup.db"` for a safe online backup). To restore: stop the app, replace the file, restart.

## CSV import

Supported on the Profile & Targets page: BP, weight, sleep, exercise. Download a template first (button next to each importer) — headers must match. Each row is validated through the same deterministic checks as manual entry; malformed or physiologically impossible rows are rejected individually and reported, the rest still import. See `app/csv_import.py`.

## Export / delete your data

Also on the Profile & Targets page:
- **Export My Data** — downloads one JSON file with everything tied to the active profile (profile, medications, meals, targets, vitals, workouts, plans, safety events).
- **Delete My Data** — deletes the profile and cascades to every table that references it. Irreversible.

## AI provider config

See the Configuration table above. The app degrades gracefully with no key configured — see [ARCHITECTURE.md](ARCHITECTURE.md) for exactly what changes.

## Privacy

- Local-first: no data leaves the machine except food lookups to USDA (if configured) and prompts to the configured AI provider (profile/health data relevant to the question, per HealthPilot's own tool calls — not your entire database).
- No health data or API keys are ever passed to `print`/`logging` (enforced by a static test — see `tests/security/test_no_secrets_in_logs.py`).
- All queries are parameterized (no string-built SQL anywhere in the codebase).
- `.env` and the SQLite database are gitignored.
- Multiple profiles are fully isolated — every table scoped to a profile is filtered by `profile_id` on every query, and deleting a profile cascades everywhere via foreign keys. See `tests/security/`.

## Known limitations

See [HANDOFF.md](HANDOFF.md) for the full list, including what browser-based acceptance testing did and didn't cover in this environment (no Playwright/Selenium was available — verification was done via direct HTTP requests against every route/endpoint a browser's JS would hit, not actual in-browser JS execution).

## Running tests

```bash
source .venv/bin/activate
python -m pytest tests/ -q
```

See [TESTING.md](TESTING.md).

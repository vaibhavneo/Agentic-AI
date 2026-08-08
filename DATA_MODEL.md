# Data Model

SQLite, one file (`data/healthpilot.db`), schema built from `migrations/*.sql` applied in filename order (tracked in `schema_migrations`). Every profile-owned table cascades on profile delete. All access is through parameterized queries in the domain service modules — no raw string-built SQL anywhere.

## Migrations

| File | Adds |
|---|---|
| `001_profiles_and_medications.sql` | `profiles`, `medications`, `medication_logs`, `safety_events` |
| `002_nutrition.sql` | `foods`, `servings`, `meals`, `meal_foods`, `nutrition_targets`, `water_logs` |
| `003_nutrition_seed_foods.sql` | ~33 seed foods + their servings (data-only migration) |
| `004_vitals.sql` | `bp_readings`, `weight_logs`, `sleep_logs`, `other_vitals_logs` |
| `005_exercise.sql` | `workouts`, `strength_sets` |
| `006_meal_planning.sql` | `weekly_plans`, `plan_days`, `plan_meals`, `plan_meal_foods` |

## Core tables

### `profiles`
Onboarding fields: name, age, sex, height_cm, current/goal weight, activity_level, diet_preference (veg/non_veg), allergies/intolerances/cuisine_preferences/disliked_foods (JSON string arrays), meals_per_day, wake/bed_time.
Clinical fields, all optional: `kidney_disease` (`yes`/`no`/`unknown`, **defaults to `unknown`, never inferred**), `egfr`, `potassium_mmol_l`, `clinician_sodium_target_mg`, `clinician_protein_target_g`, `clinician_calorie_target`.

### `medications` / `medication_logs`
A medication record has no dose-change fields anywhere — logging is limited to name/dose/frequency/schedule as prescribed, plus a daily taken/missed log. `potassium_risk` is auto-classified from a known drug-class name list (`safety/constants.py::POTASSIUM_AFFECTING_MED_PATTERNS`) or manually overridden by the user; `potassium_risk_source` records which.

### `safety_events`
Append-only audit log: every BP reading above `info` severity, tagged `severity` (`info`/`warning`/`urgent`) and a JSON `context` blob. Independent of `bp_readings.category/urgency/emergency`, which is a per-reading snapshot.

## Nutrition

### `foods` / `servings`
Per-100g nutrient columns (`calories_kcal`, `protein_g`, `carbs_g`, `fiber_g`, `total_fat_g`, `saturated_fat_g`, `sodium_mg`, `potassium_mg`, `calcium_mg`, `magnesium_mg`, `added_sugar_g`). `source` is `usda` or `manual`; seed data uses `source='manual'` with `external_id` slugs like `seed:banana`. A food has 1+ servings (`grams`, one marked `is_default`).

### `meals` / `meal_foods`
A meal is a real, already-eaten/logged entry (`meal_date`, `meal_type`, `source` = manual/nl/plan, `restaurant` flag). `meal_foods` stores the **resolved grams actually consumed** per item — totals are always computed fresh from this (`nutrition/meal_service.py::calculate_meal_nutrition`), never cached, so they can't drift from what was logged.

### `nutrition_targets`
One row per computation, never updated in place — history is kept so a past day can be evaluated against the target active at the time. `source` is `computed` or `clinician`; `protein_gate_blocked` records whether `safety/protein_safety.py` intervened.

### `water_logs`
Separate from food-derived nutrition — a simple `(profile_id, log_date, amount_ml)` log.

## Vitals

### `bp_readings`
Up to two measurements per entry (`systolic_1/diastolic_1/pulse_1`, optional `_2` set — the standard take-twice protocol). `symptoms_json` holds only entries from the fixed `safety/constants.py::BP_EMERGENCY_SYMPTOMS` checklist. `category`/`urgency`/`emergency` are a **snapshot** of what `safety/bp_safety.py` returned at record time; the human-readable message is *not* stored (cheap to regenerate deterministically from category+symptoms — see `vitals/bp_service.py::_row_to_reading`).

### `weight_logs`, `sleep_logs`, `other_vitals_logs`
Straightforward per-date logs. `sleep_logs.log_date` is the **morning-of** date (a night's sleep counts toward the day it ends on) — this matters for how `insights/pattern_engine.py` pairs sleep with BP.

## Exercise

### `workouts` / `strength_sets`
One header row per session (`workout_type` cardio/strength, `activity`, `duration_min`, and for cardio: `distance_km`, `steps`, `avg_hr`/`max_hr`, `intensity` light/moderate/vigorous — required for cardio, drives the weekly aerobic-minutes rollup). Strength sessions have 0+ `strength_sets` rows (exercise_name, set_number, reps, weight_kg, rpe). `wearable_calories` is stored as reported but a separate `conservative_dietary_credit` (75% of raw) is what any future auto-crediting feature should use — see `exercise/activity_service.py`.

## Meal planning

### `weekly_plans` → `plan_days` → `plan_meals` → `plan_meal_foods`
A **proposal**, structurally identical to (but a separate table tree from) the "already eaten" `meals`/`meal_foods` tables — planning a dinner doesn't log it as eaten. `plan_meals.locked` survives a "regenerate day" call; `plan_meals.source` is `generated`/`custom`/`restaurant`/`leftovers` (the latter two have zero `plan_meal_foods` rows — nutrition is unknown/approximate for them, so none is shown rather than a stale/fabricated number).

## Derived, not stored

Nothing here is a table because it's cheap to recompute and storing it risks drift:
- Daily/weekly nutrition totals (`nutrition/daily_service.py`)
- BP/weight averages and trends (`vitals/bp_service.py`, `vitals/weight_service.py`)
- Weekly activity rollups (`exercise/activity_service.py`)
- Health-score components, today's-insight, weekly-summary (`insights/`)
- Pattern-analysis correlations (`insights/pattern_engine.py`)

## Multi-profile isolation

Every table above except `foods`/`servings` (shared reference data) and `schema_migrations` carries `profile_id TEXT REFERENCES profiles(id) ON DELETE CASCADE`, directly or transitively (e.g. `meal_foods` cascades via `meals.profile_id`, `plan_meal_foods` via `plan_meal_id → plan_meals → plan_days → weekly_plans.profile_id`). See `tests/security/test_full_isolation.py` for the exhaustive check.

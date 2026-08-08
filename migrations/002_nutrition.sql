-- M2: nutrition. All nutrient columns are per-100g so a Food row is a fixed
-- fact regardless of how much of it gets eaten; MealFood stores the resolved
-- grams actually consumed, and totals are computed on read (calculate_*),
-- never persisted, so they can never drift out of sync with their inputs.

CREATE TABLE IF NOT EXISTS foods (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source                TEXT NOT NULL CHECK (source IN ('usda', 'manual')),
    external_id           TEXT,                 -- USDA fdcId, NULL for manual entries
    name                  TEXT NOT NULL,
    brand                 TEXT,
    calories_kcal         REAL NOT NULL,
    protein_g             REAL NOT NULL DEFAULT 0,
    carbs_g               REAL NOT NULL DEFAULT 0,
    fiber_g               REAL NOT NULL DEFAULT 0,
    total_fat_g           REAL NOT NULL DEFAULT 0,
    saturated_fat_g       REAL NOT NULL DEFAULT 0,
    sodium_mg             REAL NOT NULL DEFAULT 0,
    potassium_mg          REAL NOT NULL DEFAULT 0,
    calcium_mg            REAL NOT NULL DEFAULT 0,
    magnesium_mg          REAL NOT NULL DEFAULT 0,
    added_sugar_g         REAL NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_foods_name ON foods(name);

CREATE TABLE IF NOT EXISTS servings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    food_id      INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    description  TEXT NOT NULL,   -- e.g. "1 cup cooked", "1 medium (118g)"
    grams        REAL NOT NULL CHECK (grams > 0),
    is_default   INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_servings_food ON servings(food_id);

CREATE TABLE IF NOT EXISTS meals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    meal_type      TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
    meal_date      TEXT NOT NULL,          -- YYYY-MM-DD, local calendar day this meal counts toward
    logged_at      TEXT NOT NULL DEFAULT (datetime('now')),
    source         TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'nl', 'plan')),
    restaurant     INTEGER NOT NULL DEFAULT 0 CHECK (restaurant IN (0, 1)),
    notes          TEXT
);

CREATE INDEX IF NOT EXISTS idx_meals_profile_date ON meals(profile_id, meal_date);

CREATE TABLE IF NOT EXISTS meal_foods (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id      INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
    food_id      INTEGER NOT NULL REFERENCES foods(id),
    serving_id   INTEGER REFERENCES servings(id),
    quantity     REAL NOT NULL CHECK (quantity > 0),   -- number of servings (or grams if serving_id IS NULL)
    grams        REAL NOT NULL CHECK (grams > 0)        -- resolved actual grams eaten; deterministic totals key off this
);

CREATE INDEX IF NOT EXISTS idx_meal_foods_meal ON meal_foods(meal_id);

-- One row per (profile, effective_date): the currently-active target set.
-- History is kept (never UPDATEd in place) so past days can still be
-- evaluated against the target that was active at the time.
CREATE TABLE IF NOT EXISTS nutrition_targets (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id            TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    calories              INTEGER NOT NULL,
    protein_g             REAL NOT NULL,
    carbs_g               REAL,
    fiber_g               REAL NOT NULL,
    sodium_mg             INTEGER NOT NULL,
    potassium_mg          INTEGER,           -- informational only, see safety/potassium_safety.py
    water_ml              INTEGER NOT NULL,
    source                TEXT NOT NULL CHECK (source IN ('computed', 'clinician')),
    protein_gate_blocked  INTEGER NOT NULL DEFAULT 0 CHECK (protein_gate_blocked IN (0, 1)),
    effective_date        TEXT NOT NULL DEFAULT (date('now')),
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_nutrition_targets_profile ON nutrition_targets(profile_id, effective_date);

CREATE TABLE IF NOT EXISTS water_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    log_date     TEXT NOT NULL,
    amount_ml    INTEGER NOT NULL CHECK (amount_ml > 0),
    logged_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_water_logs_profile_date ON water_logs(profile_id, log_date);

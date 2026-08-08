-- M5: meal planning. Plans are proposals distinct from actually-logged
-- meals (nutrition.meals) — planning a dinner doesn't log it as eaten.
-- Persisted per-day/per-meal (not regenerated on read) so swapping one meal
-- never touches the rest of the week, and a lock survives a "regenerate day"
-- call.

CREATE TABLE IF NOT EXISTS weekly_plans (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    week_start     TEXT NOT NULL,   -- Monday, YYYY-MM-DD
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (profile_id, week_start)
);

CREATE TABLE IF NOT EXISTS plan_days (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    weekly_plan_id   INTEGER NOT NULL REFERENCES weekly_plans(id) ON DELETE CASCADE,
    day_date         TEXT NOT NULL,
    day_index        INTEGER NOT NULL CHECK (day_index BETWEEN 0 AND 6)
);

CREATE INDEX IF NOT EXISTS idx_plan_days_weekly_plan ON plan_days(weekly_plan_id);

CREATE TABLE IF NOT EXISTS plan_meals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_day_id  INTEGER NOT NULL REFERENCES plan_days(id) ON DELETE CASCADE,
    meal_type    TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
    locked       INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0, 1)),
    -- 'generated': from the planner. 'custom': user-specified foods.
    -- 'restaurant' / 'leftovers': marked with no foods list (nutrition unknown).
    source       TEXT NOT NULL DEFAULT 'generated' CHECK (source IN ('generated', 'custom', 'restaurant', 'leftovers')),
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_plan_meals_day ON plan_meals(plan_day_id);

CREATE TABLE IF NOT EXISTS plan_meal_foods (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_meal_id  INTEGER NOT NULL REFERENCES plan_meals(id) ON DELETE CASCADE,
    food_id       INTEGER NOT NULL REFERENCES foods(id),
    serving_id    INTEGER REFERENCES servings(id),
    quantity      REAL NOT NULL CHECK (quantity > 0),
    grams         REAL NOT NULL CHECK (grams > 0)
);

CREATE INDEX IF NOT EXISTS idx_plan_meal_foods_meal ON plan_meal_foods(plan_meal_id);

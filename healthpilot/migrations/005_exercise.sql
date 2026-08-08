-- M4: exercise. Cardio and strength share the `workouts` header row;
-- strength's per-set detail (weight/reps/RPE) lives in strength_sets since
-- a single strength session has many sets and cardio has none.

CREATE TABLE IF NOT EXISTS workouts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id         TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    workout_type       TEXT NOT NULL CHECK (workout_type IN ('cardio', 'strength')),
    activity           TEXT NOT NULL,          -- e.g. 'running', 'walking', 'cycling', 'strength_training'
    workout_date       TEXT NOT NULL,
    start_time         TEXT,
    duration_min       REAL,
    distance_km        REAL,
    steps              INTEGER,
    avg_hr             INTEGER,
    max_hr             INTEGER,
    rpe                INTEGER CHECK (rpe IS NULL OR (rpe BETWEEN 1 AND 10)),

    -- Cardio only. Drives the weekly moderate/vigorous-minutes rollup — see
    -- exercise/activity_service.py. NULL for strength workouts.
    intensity          TEXT CHECK (intensity IS NULL OR intensity IN ('light', 'moderate', 'vigorous')),

    -- Wearable-reported estimate. Deliberately never auto-credited 1:1 back
    -- to a dietary allowance — see exercise/activity_service.py's
    -- conservative_dietary_credit for the discounted figure any caller
    -- should use instead if crediting calories back at all.
    wearable_calories  REAL,

    notes              TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_workouts_profile_date ON workouts(profile_id, workout_date);

CREATE TABLE IF NOT EXISTS strength_sets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id     INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
    exercise_name  TEXT NOT NULL,
    set_number     INTEGER NOT NULL,
    reps           INTEGER NOT NULL,
    weight_kg      REAL,
    rpe            INTEGER CHECK (rpe IS NULL OR (rpe BETWEEN 1 AND 10))
);

CREATE INDEX IF NOT EXISTS idx_strength_sets_workout ON strength_sets(workout_id);

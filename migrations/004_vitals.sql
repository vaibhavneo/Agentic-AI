-- M3: BP readings, weight, sleep, and the smaller optional daily vitals.
-- Averages/trends are computed on read (vitals/bp_service.py) from these raw
-- rows, never persisted, for the same never-goes-stale reason as nutrition
-- totals (see migrations/002_nutrition.sql).

CREATE TABLE IF NOT EXISTS bp_readings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id        TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    reading_date      TEXT NOT NULL,   -- YYYY-MM-DD
    reading_time      TEXT,            -- HH:MM, optional
    systolic_1        INTEGER NOT NULL,
    diastolic_1       INTEGER NOT NULL,
    pulse_1           INTEGER,
    systolic_2        INTEGER,         -- second measurement, standard protocol; optional
    diastolic_2       INTEGER,
    pulse_2           INTEGER,
    symptoms_json     TEXT NOT NULL DEFAULT '[]',  -- entries only from safety.constants.BP_EMERGENCY_SYMPTOMS
    notes             TEXT,

    -- Snapshot of what the deterministic safety engine returned at record
    -- time (safety/bp_safety.py) — an audit trail independent of
    -- safety_events, scoped to this specific reading.
    category          TEXT NOT NULL,
    urgency           TEXT NOT NULL CHECK (urgency IN ('info', 'warning', 'urgent')),
    emergency         INTEGER NOT NULL DEFAULT 0 CHECK (emergency IN (0, 1)),

    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bp_readings_profile_date ON bp_readings(profile_id, reading_date);

CREATE TABLE IF NOT EXISTS weight_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    log_date     TEXT NOT NULL,
    weight_kg    REAL NOT NULL,
    notes        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_weight_logs_profile_date ON weight_logs(profile_id, log_date);

CREATE TABLE IF NOT EXISTS sleep_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    log_date     TEXT NOT NULL,        -- night the sleep counts toward (the morning-of date)
    hours        REAL NOT NULL,
    quality      INTEGER,              -- 1-5 self-rated, optional
    notes        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sleep_logs_profile_date ON sleep_logs(profile_id, log_date);

-- Smaller optional daily vitals: resting HR, waist, HRV, SpO2. Grouped into
-- one table since they're always single point-in-time numbers logged
-- together on a check-in, unlike BP/weight/sleep which get their own richer
-- tracking (history charts, trends) and tool functions.
CREATE TABLE IF NOT EXISTS other_vitals_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    log_date       TEXT NOT NULL,
    resting_hr     INTEGER,
    waist_cm       REAL,
    hrv_ms         REAL,
    spo2_pct       REAL,
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_other_vitals_profile_date ON other_vitals_logs(profile_id, log_date);

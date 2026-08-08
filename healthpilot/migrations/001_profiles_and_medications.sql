-- M1: profiles + medications. UUID text ids for profiles so exports/imports
-- and future multi-device sync don't depend on row order. Every other table
-- in the app carries profile_id and every query must filter by it — that is
-- what keeps multiple profiles isolated from each other (see tests/security).

CREATE TABLE IF NOT EXISTS profiles (
    id                          TEXT PRIMARY KEY,
    name                        TEXT NOT NULL,
    age                         INTEGER NOT NULL,
    sex                         TEXT NOT NULL CHECK (sex IN ('male', 'female', 'other')),
    height_cm                   REAL NOT NULL,
    current_weight_kg           REAL NOT NULL,
    goal_weight_kg              REAL,
    activity_level              TEXT NOT NULL CHECK (
        activity_level IN ('sedentary', 'light', 'moderate', 'active', 'very_active')
    ),
    diet_preference             TEXT NOT NULL CHECK (diet_preference IN ('veg', 'non_veg')),
    allergies_json              TEXT NOT NULL DEFAULT '[]',
    intolerances_json           TEXT NOT NULL DEFAULT '[]',
    cuisine_preferences_json    TEXT NOT NULL DEFAULT '[]',
    disliked_foods_json         TEXT NOT NULL DEFAULT '[]',
    meals_per_day               INTEGER NOT NULL DEFAULT 3,
    wake_time                   TEXT,
    bed_time                    TEXT,

    -- Lab / clinical values are all optional. 'unknown' is a first-class,
    -- explicitly-chosen state for kidney_disease — never inferred, never
    -- silently defaulted to 'no'. See safety/protein_safety.py.
    kidney_disease              TEXT NOT NULL DEFAULT 'unknown'
                                     CHECK (kidney_disease IN ('yes', 'no', 'unknown')),
    egfr                        REAL,
    potassium_mmol_l            REAL,

    clinician_sodium_target_mg  INTEGER,
    clinician_protein_target_g  REAL,
    clinician_calorie_target    INTEGER,

    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS medications (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id           TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name                 TEXT NOT NULL,
    dose                 TEXT,
    frequency            TEXT,
    scheduled_time       TEXT,
    notes                TEXT,

    -- Auto-classified from a known drug-class list (safety/potassium_safety.py)
    -- at write time, or explicitly set by the user for drugs we don't recognize.
    -- Informational only — this never drives dosing advice, only suppresses
    -- potassium-supplement / salt-substitute auto-recommendations downstream.
    potassium_risk           INTEGER NOT NULL DEFAULT 0 CHECK (potassium_risk IN (0, 1)),
    potassium_risk_source    TEXT NOT NULL DEFAULT 'none'
                                  CHECK (potassium_risk_source IN ('auto', 'manual', 'none')),

    active                INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_medications_profile ON medications(profile_id);

CREATE TABLE IF NOT EXISTS medication_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    medication_id   INTEGER NOT NULL REFERENCES medications(id) ON DELETE CASCADE,
    profile_id      TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    log_date        TEXT NOT NULL,
    scheduled_time  TEXT,
    taken           INTEGER NOT NULL DEFAULT 0 CHECK (taken IN (0, 1)),
    taken_at        TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_medication_logs_profile_date ON medication_logs(profile_id, log_date);

-- Append-only record of every safety-relevant decision the app surfaced
-- (BP escalation shown, potassium recommendation suppressed, protein-safety
-- gate shown, etc). Not medical advice storage — an audit trail so the
-- safety framework's behavior is reviewable and testable end-to-end.
CREATE TABLE IF NOT EXISTS safety_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id      TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    severity        TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'urgent')),
    message         TEXT NOT NULL,
    context_json    TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_safety_events_profile ON safety_events(profile_id);

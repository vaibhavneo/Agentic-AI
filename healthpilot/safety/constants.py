"""Single source of truth for every safety-relevant threshold in the app.

Nothing here is decided by the LLM — these are deterministic, reviewed
constants. Changing a threshold means editing this file, not a prompt.
"""

# --- BP thresholds (mmHg) -------------------------------------------------
# Category floors follow AHA/ACC guidance. safety/bp_safety.classify_bp checks
# these in descending order (crisis first) — a reading is classified at the
# HIGHEST category either number qualifies for, matching standard clinical
# practice (e.g. 145/78 is Stage 2 on systolic alone, despite normal diastolic).
# Deliberately expressed as floors (">=this value") rather than a min/max pair
# per category — one direction only, so there's no way for a floor and the
# previous category's ceiling to silently drift apart.
BP_STAGE_2_SYSTOLIC_FLOOR = 140
BP_STAGE_2_DIASTOLIC_FLOOR = 90
BP_STAGE_1_SYSTOLIC_FLOOR = 130
BP_STAGE_1_DIASTOLIC_FLOOR = 80
BP_ELEVATED_SYSTOLIC_FLOOR = 120
# elevated has no diastolic floor of its own — by definition it's systolic
# 120-129 with diastolic still under the Stage 1 floor (checked above it).

# >= either of these is a hypertensive crisis range — repeat-measurement /
# escalation guidance is mandatory; combined with a reported emergency
# symptom it becomes an instruction to seek emergency care. See bp_safety.py.
BP_CRISIS_SYSTOLIC_FLOOR = 180
BP_CRISIS_DIASTOLIC_FLOOR = 120

# Physiologically implausible outside this range — reject rather than store.
VALID_BP_SYSTOLIC_RANGE = (50, 300)
VALID_BP_DIASTOLIC_RANGE = (30, 200)
VALID_BP_PULSE_RANGE = (20, 250)

# Symptoms that, combined with a crisis-range reading, trigger an emergency
# instruction. Deliberately narrow and literal — matched from a fixed
# checklist in the UI, never free-text-parsed by the LLM.
BP_EMERGENCY_SYMPTOMS = {
    "chest_pain",
    "shortness_of_breath",
    "severe_headache",
    "vision_changes",
    "difficulty_speaking",
    "numbness_or_weakness",
    "confusion",
    "back_pain",
}

# --- Nutrition safety ------------------------------------------------------
DEFAULT_SODIUM_CEILING_MG = 2300  # informational default; overridden by
                                  # profile.clinician_sodium_target_mg if set

# High-protein target considered "aggressive" enough to require the kidney
# safety gate when kidney status is unknown. g/kg body weight/day.
HIGH_PROTEIN_THRESHOLD_G_PER_KG = 1.6

PROTEIN_SAFETY_GATE_MESSAGE = (
    "Confirm an appropriate protein target with your clinician before using "
    "a high-protein setting."
)

# Substrings (lower-cased) matched against a medication name to auto-flag it
# as potassium-affecting. Informational only — never used to change dosing,
# only to suppress potassium-supplement / salt-substitute auto-recommendations.
# Not exhaustive; users can also manually flag a medication.
POTASSIUM_AFFECTING_MED_PATTERNS = [
    # ARBs
    "valsartan", "losartan", "irbesartan", "olmesartan", "candesartan",
    "telmisartan", "azilsartan", "eprosartan",
    # ACE inhibitors
    "lisinopril", "enalapril", "ramipril", "benazepril", "captopril",
    "fosinopril", "perindopril", "quinapril", "trandolapril", "moexipril",
    # Potassium-sparing diuretics
    "spironolactone", "eplerenone", "amiloride", "triamterene",
    # Direct renin inhibitor
    "aliskiren",
]

# --- Generic input validation ranges ---------------------------------------
VALID_AGE_RANGE = (0, 120)
VALID_HEIGHT_CM_RANGE = (50, 250)
VALID_WEIGHT_KG_RANGE = (20, 400)
VALID_MEALS_PER_DAY_RANGE = (1, 10)
VALID_EGFR_RANGE = (0, 200)
VALID_POTASSIUM_RANGE = (1.5, 9.0)  # mmol/L, physiologically plausible bounds
VALID_SODIUM_TARGET_RANGE = (500, 6000)  # mg
VALID_PROTEIN_TARGET_RANGE = (10, 400)  # g
VALID_CALORIE_TARGET_RANGE = (800, 6000)

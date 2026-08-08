"""Profile model: validation + CRUD. All reads/writes are parameterized SQL
and scoped by profile id — the isolation boundary the rest of the app relies
on (see tests/security/test_multi_profile_isolation.py)."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from database.db import get_connection
from safety.constants import (
    VALID_AGE_RANGE,
    VALID_HEIGHT_CM_RANGE,
    VALID_WEIGHT_KG_RANGE,
    VALID_MEALS_PER_DAY_RANGE,
    VALID_EGFR_RANGE,
    VALID_POTASSIUM_RANGE,
    VALID_SODIUM_TARGET_RANGE,
    VALID_PROTEIN_TARGET_RANGE,
    VALID_CALORIE_TARGET_RANGE,
)

VALID_SEX = {"male", "female", "other"}
VALID_ACTIVITY_LEVELS = {"sedentary", "light", "moderate", "active", "very_active"}
VALID_DIET_PREFS = {"veg", "non_veg"}
VALID_KIDNEY_STATES = {"yes", "no", "unknown"}

_JSON_LIST_FIELDS = ("allergies", "intolerances", "cuisine_preferences", "disliked_foods")


class ValidationError(ValueError):
    pass


def _require_range(name: str, value, lo, hi):
    if value is None:
        return
    if not (lo <= value <= hi):
        raise ValidationError(f"{name} must be between {lo} and {hi}, got {value}")


def _validate_time_str(name: str, value: str | None):
    if value is None or value == "":
        return
    parts = value.split(":")
    if len(parts) != 2:
        raise ValidationError(f"{name} must be HH:MM, got {value!r}")
    h, m = parts
    if not (h.isdigit() and m.isdigit() and 0 <= int(h) <= 23 and 0 <= int(m) <= 59):
        raise ValidationError(f"{name} must be a valid HH:MM time, got {value!r}")


def validate_profile_input(data: dict) -> dict:
    """Validates and normalizes profile input. Raises ValidationError on any
    malformed or physiologically impossible value — never silently coerces."""
    errors = []
    out = dict(data)

    if not out.get("name") or not str(out["name"]).strip():
        errors.append("name is required")

    try:
        out["age"] = int(out["age"])
        _require_range("age", out["age"], *VALID_AGE_RANGE)
    except (KeyError, TypeError, ValueError) as e:
        errors.append(f"age: {e}" if isinstance(e, ValidationError) else "age is required and must be an integer")

    if out.get("sex") not in VALID_SEX:
        errors.append(f"sex must be one of {sorted(VALID_SEX)}")

    try:
        out["height_cm"] = float(out["height_cm"])
        _require_range("height_cm", out["height_cm"], *VALID_HEIGHT_CM_RANGE)
    except (KeyError, TypeError, ValueError):
        errors.append("height_cm is required and must be a number")

    try:
        out["current_weight_kg"] = float(out["current_weight_kg"])
        _require_range("current_weight_kg", out["current_weight_kg"], *VALID_WEIGHT_KG_RANGE)
    except (KeyError, TypeError, ValueError):
        errors.append("current_weight_kg is required and must be a number")

    if out.get("goal_weight_kg") not in (None, ""):
        try:
            out["goal_weight_kg"] = float(out["goal_weight_kg"])
            _require_range("goal_weight_kg", out["goal_weight_kg"], *VALID_WEIGHT_KG_RANGE)
        except (TypeError, ValueError):
            errors.append("goal_weight_kg must be a number")
    else:
        out["goal_weight_kg"] = None

    if out.get("activity_level") not in VALID_ACTIVITY_LEVELS:
        errors.append(f"activity_level must be one of {sorted(VALID_ACTIVITY_LEVELS)}")

    if out.get("diet_preference") not in VALID_DIET_PREFS:
        errors.append(f"diet_preference must be one of {sorted(VALID_DIET_PREFS)}")

    for f in _JSON_LIST_FIELDS:
        val = out.get(f, [])
        if val is None:
            val = []
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            errors.append(f"{f} must be a list of strings")
        out[f] = val

    try:
        out["meals_per_day"] = int(out.get("meals_per_day", 3))
        _require_range("meals_per_day", out["meals_per_day"], *VALID_MEALS_PER_DAY_RANGE)
    except (TypeError, ValueError):
        errors.append("meals_per_day must be an integer")

    try:
        _validate_time_str("wake_time", out.get("wake_time"))
        _validate_time_str("bed_time", out.get("bed_time"))
    except ValidationError as e:
        errors.append(str(e))

    if out.get("kidney_disease", "unknown") not in VALID_KIDNEY_STATES:
        errors.append(f"kidney_disease must be one of {sorted(VALID_KIDNEY_STATES)}")
    out.setdefault("kidney_disease", "unknown")

    for f, rng in (
        ("egfr", VALID_EGFR_RANGE),
        ("potassium_mmol_l", VALID_POTASSIUM_RANGE),
    ):
        if out.get(f) not in (None, ""):
            try:
                out[f] = float(out[f])
                _require_range(f, out[f], *rng)
            except (TypeError, ValueError) as e:
                errors.append(f"{f}: {e}" if isinstance(e, ValidationError) else f"{f} must be a number")
        else:
            out[f] = None

    for f, rng, caster in (
        ("clinician_sodium_target_mg", VALID_SODIUM_TARGET_RANGE, int),
        ("clinician_protein_target_g", VALID_PROTEIN_TARGET_RANGE, float),
        ("clinician_calorie_target", VALID_CALORIE_TARGET_RANGE, int),
    ):
        if out.get(f) not in (None, ""):
            try:
                out[f] = caster(out[f])
                _require_range(f, out[f], *rng)
            except (TypeError, ValueError) as e:
                errors.append(f"{f}: {e}" if isinstance(e, ValidationError) else f"{f} must be a number")
        else:
            out[f] = None

    for f in ("primary_health_goals", "exercise_limitations"):
        val = out.get(f)
        out[f] = val.strip() if isinstance(val, str) and val.strip() else None

    if errors:
        raise ValidationError("; ".join(errors))
    return out


def create_profile(data: dict) -> dict:
    v = validate_profile_input(data)
    profile_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute(
        """INSERT INTO profiles (
            id, name, age, sex, height_cm, current_weight_kg, goal_weight_kg,
            activity_level, diet_preference, allergies_json, intolerances_json,
            cuisine_preferences_json, disliked_foods_json, meals_per_day,
            wake_time, bed_time, kidney_disease, egfr, potassium_mmol_l,
            clinician_sodium_target_mg, clinician_protein_target_g, clinician_calorie_target,
            primary_health_goals, exercise_limitations
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            profile_id, v["name"].strip(), v["age"], v["sex"], v["height_cm"],
            v["current_weight_kg"], v["goal_weight_kg"], v["activity_level"],
            v["diet_preference"], json.dumps(v["allergies"]), json.dumps(v["intolerances"]),
            json.dumps(v["cuisine_preferences"]), json.dumps(v["disliked_foods"]),
            v["meals_per_day"], v.get("wake_time"), v.get("bed_time"), v["kidney_disease"],
            v["egfr"], v["potassium_mmol_l"], v["clinician_sodium_target_mg"],
            v["clinician_protein_target_g"], v["clinician_calorie_target"],
            v["primary_health_goals"], v["exercise_limitations"],
        ),
    )
    conn.commit()
    return get_profile(profile_id)


def _row_to_dict(row) -> dict:
    d = dict(row)
    for json_field, key in (
        ("allergies_json", "allergies"),
        ("intolerances_json", "intolerances"),
        ("cuisine_preferences_json", "cuisine_preferences"),
        ("disliked_foods_json", "disliked_foods"),
    ):
        d[key] = json.loads(d.pop(json_field))
    return d


def get_profile(profile_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_profiles() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM profiles ORDER BY created_at").fetchall()
    return [_row_to_dict(r) for r in rows]


def update_profile(profile_id: str, data: dict) -> dict:
    existing = get_profile(profile_id)
    if existing is None:
        raise ValidationError(f"no such profile: {profile_id}")
    merged = {**existing, **data}
    v = validate_profile_input(merged)
    conn = get_connection()
    conn.execute(
        """UPDATE profiles SET
            name=?, age=?, sex=?, height_cm=?, current_weight_kg=?, goal_weight_kg=?,
            activity_level=?, diet_preference=?, allergies_json=?, intolerances_json=?,
            cuisine_preferences_json=?, disliked_foods_json=?, meals_per_day=?,
            wake_time=?, bed_time=?, kidney_disease=?, egfr=?, potassium_mmol_l=?,
            clinician_sodium_target_mg=?, clinician_protein_target_g=?, clinician_calorie_target=?,
            primary_health_goals=?, exercise_limitations=?,
            updated_at=datetime('now')
        WHERE id=?""",
        (
            v["name"].strip(), v["age"], v["sex"], v["height_cm"], v["current_weight_kg"],
            v["goal_weight_kg"], v["activity_level"], v["diet_preference"],
            json.dumps(v["allergies"]), json.dumps(v["intolerances"]),
            json.dumps(v["cuisine_preferences"]), json.dumps(v["disliked_foods"]),
            v["meals_per_day"], v.get("wake_time"), v.get("bed_time"), v["kidney_disease"],
            v["egfr"], v["potassium_mmol_l"], v["clinician_sodium_target_mg"],
            v["clinician_protein_target_g"], v["clinician_calorie_target"],
            v["primary_health_goals"], v["exercise_limitations"],
            profile_id,
        ),
    )
    conn.commit()
    return get_profile(profile_id)


def delete_profile(profile_id: str) -> None:
    """Cascades to every table referencing profile_id via ON DELETE CASCADE."""
    conn = get_connection()
    conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    conn.commit()

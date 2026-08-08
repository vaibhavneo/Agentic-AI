"""Nutrition target computation: calories via Mifflin-St Jeor + activity
multiplier + goal adjustment, protein via body weight/activity (gated by
safety/protein_safety.py), fiber via the IOM 14g/1000kcal guideline, sodium
from safety/constants.py's default ceiling unless a clinician target is on
file. A clinician-provided value always wins over anything computed here.
"""
from __future__ import annotations

import datetime as dt

from database.db import get_connection
from safety.constants import DEFAULT_SODIUM_CEILING_MG
from safety.protein_safety import check_protein_target_safety

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

# g of protein per kg body weight, before the safety gate is applied.
PROTEIN_G_PER_KG = {
    "sedentary": 0.8,
    "light": 1.0,
    "moderate": 1.2,
    "active": 1.4,
    "very_active": 1.6,
}

CONSERVATIVE_PROTEIN_G_PER_KG = 0.8  # RDA baseline, used when the gate blocks the personalized target
MIN_CALORIE_FLOOR = 1200
WATER_ML_PER_KG = 30


def _bmr_kcal(weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "male":
        return base + 5
    if sex == "female":
        return base - 161
    return base - 78  # midpoint, used for sex == 'other'


def compute_nutrition_targets(profile: dict) -> dict:
    weight = profile["current_weight_kg"]
    bmr = _bmr_kcal(weight, profile["height_cm"], profile["age"], profile["sex"])
    tdee = bmr * ACTIVITY_MULTIPLIERS[profile["activity_level"]]

    if profile.get("clinician_calorie_target"):
        calories = profile["clinician_calorie_target"]
    else:
        goal = profile.get("goal_weight_kg")
        adjustment = 0
        if goal and abs(goal - weight) > 0.5:
            adjustment = -500 if goal < weight else 400
        calories = max(MIN_CALORIE_FLOOR, round(tdee + adjustment))

    protein_target = weight * PROTEIN_G_PER_KG[profile["activity_level"]]
    allowed, warning = check_protein_target_safety(
        protein_target, weight, profile["kidney_disease"], profile.get("clinician_protein_target_g")
    )
    protein_gate_blocked = not allowed
    if profile.get("clinician_protein_target_g"):
        protein_g = profile["clinician_protein_target_g"]
    elif protein_gate_blocked:
        protein_g = round(weight * CONSERVATIVE_PROTEIN_G_PER_KG, 1)
    else:
        protein_g = round(protein_target, 1)

    fiber_g = round(14 * calories / 1000, 1)

    sodium_mg = profile.get("clinician_sodium_target_mg") or DEFAULT_SODIUM_CEILING_MG

    water_ml = max(1500, min(4000, round(weight * WATER_ML_PER_KG)))

    return {
        "calories": calories,
        "protein_g": protein_g,
        "carbs_g": None,
        "fiber_g": fiber_g,
        "sodium_mg": sodium_mg,
        "potassium_mg": None,  # informational dietary potassium tracking only — see safety/potassium_safety.py for the supplement-recommendation gate
        "water_ml": water_ml,
        "protein_gate_blocked": protein_gate_blocked,
        "protein_gate_message": warning,
        "source": "clinician" if (profile.get("clinician_calorie_target") or profile.get("clinician_protein_target_g")) else "computed",
    }


def store_target(profile_id: str, target: dict) -> dict:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO nutrition_targets
            (profile_id, calories, protein_g, carbs_g, fiber_g, sodium_mg, potassium_mg,
             water_ml, source, protein_gate_blocked, effective_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            profile_id, target["calories"], target["protein_g"], target.get("carbs_g"),
            target["fiber_g"], target["sodium_mg"], target.get("potassium_mg"), target["water_ml"],
            target["source"], int(target.get("protein_gate_blocked", False)), dt.date.today().isoformat(),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM nutrition_targets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def recompute_and_store_target(profile: dict) -> dict:
    target = compute_nutrition_targets(profile)
    stored = store_target(profile["id"], target)
    stored["protein_gate_message"] = target["protein_gate_message"]
    return stored


def get_active_target(profile_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM nutrition_targets WHERE profile_id = ? ORDER BY effective_date DESC, id DESC LIMIT 1",
        (profile_id,),
    ).fetchone()
    return dict(row) if row else None


def get_remaining_nutrition_targets(profile_id: str, daily_totals: dict, target_date: str | None = None) -> dict:
    """daily_totals: the dict returned by nutrition.daily_service.calculate_daily_nutrition."""
    target = get_active_target(profile_id)
    if target is None:
        return {"target_set": False}

    consumed = daily_totals["totals"]
    fields = {
        "calories": ("calories_kcal", target["calories"]),
        "protein_g": ("protein_g", target["protein_g"]),
        "fiber_g": ("fiber_g", target["fiber_g"]),
        "sodium_mg": ("sodium_mg", target["sodium_mg"]),
    }
    result = {"target_set": True, "by_nutrient": {}}
    for label, (consumed_key, target_val) in fields.items():
        consumed_val = consumed.get(consumed_key, 0)
        result["by_nutrient"][label] = {
            "target": target_val,
            "consumed": round(consumed_val, 1),
            "remaining": round(target_val - consumed_val, 1),
        }
    result["by_nutrient"]["water_ml"] = {
        "target": target["water_ml"],
        "consumed": daily_totals["water_ml"],
        "remaining": target["water_ml"] - daily_totals["water_ml"],
    }
    return result

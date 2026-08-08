"""Deterministic BP safety engine. Every threshold and every message here is
fixed at review time, in safety/constants.py — nothing about classification,
urgency, or the emergency instruction is ever decided by the LLM.

Hard rules this module must never violate:
  1. classify_bp is pure arithmetic — no model call, no randomness.
  2. No return path here ever names a medication, an exercise, or a food/diet
     action as something to do about the reading. Acute BP management is a
     clinical decision; this module's job stops at "here's the category and
     whether to escalate."
  3. Symptoms are only ever matched against the fixed BP_EMERGENCY_SYMPTOMS
     checklist (safety/constants.py) — never free-text/LLM-parsed. Any value
     outside that set is rejected, not best-effort interpreted.
  4. A crisis-range reading ALWAYS gets repeat-measurement/escalation
     guidance, regardless of symptoms. Adding a reported emergency symptom on
     top of a crisis-range reading is what upgrades that to an emergency
     instruction — never used as the sole trigger by itself.
"""
from __future__ import annotations

from safety.constants import (
    BP_CRISIS_DIASTOLIC_FLOOR,
    BP_CRISIS_SYSTOLIC_FLOOR,
    BP_ELEVATED_SYSTOLIC_FLOOR,
    BP_EMERGENCY_SYMPTOMS,
    BP_STAGE_1_DIASTOLIC_FLOOR,
    BP_STAGE_1_SYSTOLIC_FLOOR,
    BP_STAGE_2_DIASTOLIC_FLOOR,
    BP_STAGE_2_SYSTOLIC_FLOOR,
)

CATEGORIES_IN_SEVERITY_ORDER = ("normal", "elevated", "stage_1", "stage_2", "crisis")


class BPSafetyError(ValueError):
    pass


def classify_bp(systolic: int, diastolic: int) -> str:
    """Returns one of CATEGORIES_IN_SEVERITY_ORDER. A reading is classified
    at the HIGHEST category either number alone qualifies for — e.g. 145/78
    is 'stage_2' despite a normal diastolic, matching standard clinical
    practice of taking the more severe of the two readings."""
    if systolic >= BP_CRISIS_SYSTOLIC_FLOOR or diastolic >= BP_CRISIS_DIASTOLIC_FLOOR:
        return "crisis"
    if systolic >= BP_STAGE_2_SYSTOLIC_FLOOR or diastolic >= BP_STAGE_2_DIASTOLIC_FLOOR:
        return "stage_2"
    if systolic >= BP_STAGE_1_SYSTOLIC_FLOOR or diastolic >= BP_STAGE_1_DIASTOLIC_FLOOR:
        return "stage_1"
    if systolic >= BP_ELEVATED_SYSTOLIC_FLOOR:
        return "elevated"
    return "normal"


def validate_symptoms(symptoms: list[str] | None) -> list[str]:
    symptoms = symptoms or []
    invalid = set(symptoms) - BP_EMERGENCY_SYMPTOMS
    if invalid:
        raise BPSafetyError(
            f"unrecognized symptom(s): {sorted(invalid)} — must be from the fixed checklist {sorted(BP_EMERGENCY_SYMPTOMS)}"
        )
    return list(symptoms)


_MESSAGES = {
    "normal": "This reading is in the normal range.",
    "elevated": "This reading is slightly elevated. A single reading isn't a diagnosis — keep tracking over time.",
    "stage_1": "This reading is in the Stage 1 range. A pattern over several readings matters more than any single one — keep tracking.",
    "stage_2": (
        "This reading is elevated (Stage 2 range). Rest a few minutes and take another reading to confirm. "
        "If readings stay this high over the next few days, contact your clinician."
    ),
    "crisis": (
        "This reading is in a dangerously high range. Sit down and rest for 5 minutes, then take a second "
        "reading. If it remains this high, contact your clinician today or seek urgent care."
    ),
    "crisis_emergency": (
        "This reading, combined with the symptoms you reported, can indicate a hypertensive emergency. "
        "Seek emergency medical care immediately — call your local emergency number or go to the nearest "
        "emergency room now. Do not wait to see if it improves on its own."
    ),
}


def evaluate_bp_reading(systolic: int, diastolic: int, symptoms: list[str] | None = None) -> dict:
    """Pure function: classification + guidance for one BP reading. No DB
    access, no side effects — vitals/bp_service.py is responsible for
    persisting the reading and logging a safety_event when warranted."""
    symptoms = validate_symptoms(symptoms)
    category = classify_bp(systolic, diastolic)
    is_crisis = category == "crisis"
    emergency = is_crisis and len(symptoms) > 0

    if emergency:
        urgency = "urgent"
        message = _MESSAGES["crisis_emergency"]
        repeat_measurement_recommended = False  # don't delay seeking care for a second reading
    elif is_crisis:
        urgency = "urgent"
        message = _MESSAGES["crisis"]
        repeat_measurement_recommended = True
    elif category == "stage_2":
        urgency = "warning"
        message = _MESSAGES["stage_2"]
        repeat_measurement_recommended = True
    else:
        urgency = "info"
        message = _MESSAGES[category]
        repeat_measurement_recommended = False

    return {
        "category": category,
        "systolic": systolic,
        "diastolic": diastolic,
        "symptoms": symptoms,
        "urgency": urgency,
        "emergency": emergency,
        "repeat_measurement_recommended": repeat_measurement_recommended,
        "message": message,
    }

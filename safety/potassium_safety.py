"""Potassium safety: flags medications that can raise serum potassium, and
gates any auto-recommendation of potassium supplements or salt substitutes.

This module never recommends a supplement itself — it only answers "is it
safe to auto-recommend one," which callers (e.g. the nutrition/heart-health
agents in later milestones) must check before doing so.
"""
from __future__ import annotations

from safety.constants import POTASSIUM_AFFECTING_MED_PATTERNS


def classify_medication_potassium_risk(medication_name: str) -> bool:
    """Deterministic substring match against a known drug-class list.
    Returns True if the name matches a class known to raise potassium."""
    if not medication_name:
        return False
    name = medication_name.strip().lower()
    return any(pattern in name for pattern in POTASSIUM_AFFECTING_MED_PATTERNS)


def profile_has_potassium_risk_medication(medications: list[dict]) -> bool:
    """medications: list of medication rows/dicts with 'potassium_risk' and
    'active' keys, as returned by app.medication.list_medications()."""
    return any(
        m.get("active", True) and m.get("potassium_risk")
        for m in medications
    )


def can_auto_recommend_potassium_supplement(medications: list[dict]) -> tuple[bool, str | None]:
    """Returns (allowed, reason_if_blocked). The safety framework blocks
    auto-recommending potassium supplements or salt substitutes whenever the
    user is on ANY active potassium-affecting medication — the risk of
    hyperkalemia outweighs the benefit of an automated suggestion. A
    clinician can still advise this directly; the app just won't."""
    if profile_has_potassium_risk_medication(medications):
        return False, (
            "This profile has an active medication that can raise potassium "
            "(e.g. an ARB, ACE inhibitor, or potassium-sparing diuretic). "
            "Potassium supplements and salt substitutes are not auto-"
            "recommended — discuss potassium intake with your clinician."
        )
    return True, None

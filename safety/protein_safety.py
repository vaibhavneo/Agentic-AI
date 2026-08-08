"""Protein safety gate: never hard-code an aggressive high-protein target,
and require clinician confirmation whenever kidney status is unknown and a
high-protein setting is in play.
"""
from __future__ import annotations

from safety.constants import HIGH_PROTEIN_THRESHOLD_G_PER_KG, PROTEIN_SAFETY_GATE_MESSAGE


def is_high_protein_target(target_g_per_day: float, weight_kg: float) -> bool:
    if weight_kg <= 0:
        return False
    return (target_g_per_day / weight_kg) >= HIGH_PROTEIN_THRESHOLD_G_PER_KG


def check_protein_target_safety(
    target_g_per_day: float,
    weight_kg: float,
    kidney_disease: str,
    clinician_protein_target_g: float | None,
) -> tuple[bool, str | None]:
    """Returns (allowed, warning_message).

    - A clinician-provided target always overrides this gate — it's already
      been reviewed by a professional.
    - kidney_disease == 'yes': never allow an app-generated high-protein
      target; caller must use a conservative default and surface the gate
      message directing the user to their clinician.
    - kidney_disease == 'unknown' and target is high: allowed=False, with
      the exact confirmation message required by the safety spec.
    - Otherwise: allowed.
    """
    if clinician_protein_target_g is not None:
        return True, None

    if not is_high_protein_target(target_g_per_day, weight_kg):
        return True, None

    if kidney_disease in ("yes", "unknown"):
        return False, PROTEIN_SAFETY_GATE_MESSAGE

    return True, None

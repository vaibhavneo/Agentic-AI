from __future__ import annotations

from app.medication import get_medication_context as _get_medication_context


def get_medication_context(profile_id: str) -> dict:
    return _get_medication_context(profile_id)

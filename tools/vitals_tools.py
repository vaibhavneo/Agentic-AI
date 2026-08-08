"""Deterministic vitals tools for the AI agents (M6) — same pattern as
tools/nutrition_tools.py: thin, JSON-in/JSON-out wrappers over real logic.
"""
from __future__ import annotations

from vitals.bp_service import (
    calculate_bp_average as _calculate_bp_average,
    calculate_bp_trend as _calculate_bp_trend,
    get_bp_history as _get_bp_history,
    get_latest_bp_reading as _get_latest_bp_reading,
    record_bp as _record_bp,
)
from vitals.sleep_service import get_sleep_history as _get_sleep_history
from vitals.sleep_service import record_sleep as _record_sleep
from vitals.weight_service import get_weight_history as _get_weight_history
from vitals.weight_service import record_weight as _record_weight


def record_bp(profile_id: str, systolic_1: int, diastolic_1: int, **kwargs) -> dict:
    return _record_bp(profile_id, systolic_1, diastolic_1, **kwargs)


def get_bp_history(profile_id: str, days: int = 30) -> list[dict]:
    return _get_bp_history(profile_id, days)


def get_latest_bp_reading(profile_id: str) -> dict | None:
    return _get_latest_bp_reading(profile_id)


def calculate_bp_average(profile_id: str, days: int = 7) -> dict:
    return _calculate_bp_average(profile_id, days)


def calculate_bp_trend(profile_id: str, days: int = 30) -> dict:
    return _calculate_bp_trend(profile_id, days)


def record_weight(profile_id: str, weight_kg: float, **kwargs) -> dict:
    return _record_weight(profile_id, weight_kg, **kwargs)


def get_weight_history(profile_id: str, days: int = 90) -> list[dict]:
    return _get_weight_history(profile_id, days)


def record_sleep(profile_id: str, hours: float, **kwargs) -> dict:
    return _record_sleep(profile_id, hours, **kwargs)


def get_sleep_history(profile_id: str, days: int = 30) -> list[dict]:
    return _get_sleep_history(profile_id, days)

"""Shared input-validation helpers used across domain services."""
from __future__ import annotations

import datetime as dt


def validate_date_str(name: str, value: str) -> str:
    """Raises ValueError if value isn't a real YYYY-MM-DD date. Every
    *_date/log_date parameter across the app should be checked with this
    before being stored — an unvalidated date string silently breaks
    chronological queries (get_*_history's date-range filters compare dates
    as strings) and could otherwise carry arbitrary attacker-controlled text
    into a date column."""
    try:
        dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a valid YYYY-MM-DD date, got {value!r}")
    return value

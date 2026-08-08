from __future__ import annotations

from exercise.activity_service import get_today_activity as _get_today_activity
from exercise.activity_service import get_weekly_activity as _get_weekly_activity
from exercise.activity_service import log_workout as _log_workout


def log_workout(profile_id: str, workout_type: str, activity: str, **kwargs) -> dict:
    return _log_workout(profile_id, workout_type, activity, **kwargs)


def get_today_activity(profile_id: str) -> dict:
    return _get_today_activity(profile_id)


def get_weekly_activity(profile_id: str, week_start: str | None = None) -> dict:
    return _get_weekly_activity(profile_id, week_start)

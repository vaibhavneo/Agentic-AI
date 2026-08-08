"""Deterministic tool functions the AI agents (M6) call. Every function here
does real work against the database — no prompt-only stand-ins. Each tool
takes/returns plain JSON-serializable dicts so it can be handed to an LLM
tool-calling loop unchanged.
"""
from __future__ import annotations

from app.profile import get_profile
from nutrition import food_service, meal_service
from nutrition.daily_service import calculate_daily_nutrition as _calculate_daily_nutrition
from nutrition.daily_service import get_today_nutrition as _get_today_nutrition
from nutrition.targets import get_remaining_nutrition_targets as _get_remaining_nutrition_targets


def get_user_profile(profile_id: str) -> dict:
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError(f"no such profile: {profile_id}")
    return profile


def get_today_nutrition(profile_id: str) -> dict:
    return _get_today_nutrition(profile_id)


def search_food(query: str, limit: int = 10) -> list[dict]:
    return food_service.search_food(query, limit=limit)


def log_food(profile_id: str, meal_type: str, food_id: int, serving_id: int | None, quantity: float, meal_date: str | None = None) -> dict:
    return meal_service.log_food(profile_id, meal_type, food_id, serving_id, quantity, meal_date=meal_date)


def calculate_meal_nutrition(meal_id: int, profile_id: str) -> dict:
    return meal_service.calculate_meal_nutrition(meal_id, profile_id)


def calculate_daily_nutrition(profile_id: str, target_date: str | None = None) -> dict:
    return _calculate_daily_nutrition(profile_id, target_date)


def get_remaining_nutrition_targets(profile_id: str, target_date: str | None = None) -> dict:
    totals = _calculate_daily_nutrition(profile_id, target_date)
    return _get_remaining_nutrition_targets(profile_id, totals, target_date)

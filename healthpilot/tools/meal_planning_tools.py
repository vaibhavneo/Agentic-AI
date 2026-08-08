from __future__ import annotations

from app.profile import get_profile
from meal_planning.daily_planner import generate_daily_plan as _generate_daily_plan
from meal_planning.daily_planner import generate_remaining_daily_plan as _generate_remaining_daily_plan
from meal_planning.grocery import build_grocery_list as _build_grocery_list
from meal_planning.weekly_planner import create_weekly_plan, get_weekly_plan
from meal_planning.weekly_planner import swap_meal as _swap_meal


def generate_daily_plan(profile_id: str) -> dict:
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError(f"no such profile: {profile_id}")
    return _generate_daily_plan(profile)


def generate_remaining_daily_plan(profile_id: str) -> dict:
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError(f"no such profile: {profile_id}")
    return _generate_remaining_daily_plan(profile)


def generate_weekly_plan(profile_id: str, week_start: str | None = None) -> dict:
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError(f"no such profile: {profile_id}")
    return create_weekly_plan(profile, week_start)


def swap_meal(plan_meal_id: int, profile_id: str) -> dict:
    profile = get_profile(profile_id)
    if profile is None:
        raise ValueError(f"no such profile: {profile_id}")
    return _swap_meal(plan_meal_id, profile_id, profile)


def build_grocery_list(profile_id: str, week_start: str) -> dict:
    plan = get_weekly_plan(profile_id, week_start)
    return _build_grocery_list(plan)

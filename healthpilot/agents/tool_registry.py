"""Maps a tool name to a callable(profile_id, args_dict) -> JSON-serializable
result. This is the ONLY surface the chat agentic loop can reach — every
entry is a thin call into the real deterministic tools/* modules already
used by the rest of the app (nutrition/vitals/exercise/meal-planning
services). profile_id is always injected by the orchestrator from the
authenticated session, never taken from model-supplied arguments — see
agents/orchestrator.py's tool-call handling.

Deliberately read-only / non-persisting: nothing here writes a BP reading,
meal, workout, or plan. Data entry happens through the dedicated UI forms
(each with its own deterministic validation), not through freeform chat —
see ARCHITECTURE.md for the reasoning.
"""
from __future__ import annotations

from tools import exercise_tools, insights_tools, medication_tools, meal_planning_tools, nutrition_tools, vitals_tools


def _get_user_profile(profile_id, args):
    return nutrition_tools.get_user_profile(profile_id)


def _get_today_nutrition(profile_id, args):
    return nutrition_tools.get_today_nutrition(profile_id)


def _search_food(profile_id, args):
    return nutrition_tools.search_food(args["query"], limit=args.get("limit", 10))


def _calculate_daily_nutrition(profile_id, args):
    return nutrition_tools.calculate_daily_nutrition(profile_id, args.get("target_date"))


def _get_remaining_nutrition_targets(profile_id, args):
    return nutrition_tools.get_remaining_nutrition_targets(profile_id, args.get("target_date"))


def _get_bp_history(profile_id, args):
    return vitals_tools.get_bp_history(profile_id, args.get("days", 30))


def _get_latest_bp_reading(profile_id, args):
    return vitals_tools.get_latest_bp_reading(profile_id)


def _calculate_bp_average(profile_id, args):
    return vitals_tools.calculate_bp_average(profile_id, args.get("days", 7))


def _calculate_bp_trend(profile_id, args):
    return vitals_tools.calculate_bp_trend(profile_id, args.get("days", 30))


def _get_today_activity(profile_id, args):
    return exercise_tools.get_today_activity(profile_id)


def _get_weekly_activity(profile_id, args):
    return exercise_tools.get_weekly_activity(profile_id, args.get("week_start"))


def _get_weight_history(profile_id, args):
    return vitals_tools.get_weight_history(profile_id, args.get("days", 90))


def _get_sleep_history(profile_id, args):
    return vitals_tools.get_sleep_history(profile_id, args.get("days", 30))


def _get_medication_context(profile_id, args):
    return medication_tools.get_medication_context(profile_id)


def _analyze_health_patterns(profile_id, args):
    return insights_tools.analyze_health_patterns(profile_id)


def _generate_daily_plan(profile_id, args):
    return meal_planning_tools.generate_daily_plan(profile_id)


TOOL_REGISTRY = {
    "get_user_profile": _get_user_profile,
    "get_today_nutrition": _get_today_nutrition,
    "search_food": _search_food,
    "calculate_daily_nutrition": _calculate_daily_nutrition,
    "get_remaining_nutrition_targets": _get_remaining_nutrition_targets,
    "get_bp_history": _get_bp_history,
    "get_latest_bp_reading": _get_latest_bp_reading,
    "calculate_bp_average": _calculate_bp_average,
    "calculate_bp_trend": _calculate_bp_trend,
    "get_today_activity": _get_today_activity,
    "get_weekly_activity": _get_weekly_activity,
    "get_weight_history": _get_weight_history,
    "get_sleep_history": _get_sleep_history,
    "get_medication_context": _get_medication_context,
    "analyze_health_patterns": _analyze_health_patterns,
    "generate_daily_plan": _generate_daily_plan,
}


def execute_tool(tool_name: str, profile_id: str, args: dict) -> dict:
    args = dict(args or {})
    args.pop("profile_id", None)
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {"error": f"unknown tool: {tool_name}"}
    try:
        return fn(profile_id, args)
    except Exception as e:
        return {"error": str(e)}

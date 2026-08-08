"""OpenAI/DeepSeek-compatible function-calling schemas for every tool in
agents/tool_registry.py. profile_id is intentionally NOT a parameter here —
it's injected server-side, never supplied by the model (see tool_registry.execute_tool).
"""
from __future__ import annotations

_SPECS = {
    "get_user_profile": {
        "description": "Get the user's profile: age, sex, activity level, diet preference, allergies, kidney status, clinician targets.",
        "properties": {},
    },
    "get_today_nutrition": {
        "description": "Get today's logged meals and total calories/protein/carbs/fiber/sodium/potassium/water consumed so far.",
        "properties": {},
    },
    "search_food": {
        "description": "Search the food database for nutrition information by name.",
        "properties": {"query": {"type": "string", "description": "food name to search for"}, "limit": {"type": "integer"}},
        "required": ["query"],
    },
    "calculate_daily_nutrition": {
        "description": "Get total nutrition consumed on a specific date (defaults to today).",
        "properties": {"target_date": {"type": "string", "description": "YYYY-MM-DD, omit for today"}},
    },
    "get_remaining_nutrition_targets": {
        "description": "Get target vs. consumed vs. remaining for calories, protein, fiber, sodium, and water for a given date (defaults to today).",
        "properties": {"target_date": {"type": "string", "description": "YYYY-MM-DD, omit for today"}},
    },
    "get_bp_history": {
        "description": "Get blood pressure readings over the last N days, each with category/urgency/emergency flag.",
        "properties": {"days": {"type": "integer", "description": "lookback window, default 30"}},
    },
    "get_latest_bp_reading": {
        "description": "Get the single most recent blood pressure reading (regardless of what date it was logged), with category and time of day (morning/evening).",
        "properties": {},
    },
    "calculate_bp_average": {
        "description": "Get the average systolic/diastolic BP and variability over the last N days.",
        "properties": {"days": {"type": "integer", "description": "default 7"}},
    },
    "calculate_bp_trend": {
        "description": "Get whether BP is rising, falling, or stable over the last N days (compares recent half vs older half).",
        "properties": {"days": {"type": "integer", "description": "default 30"}},
    },
    "get_today_activity": {
        "description": "Get today's logged workouts, steps, and distance.",
        "properties": {},
    },
    "get_weekly_activity": {
        "description": "Get this week's (or a specified week's) moderate/vigorous aerobic minutes, strength days, distance, and steps.",
        "properties": {"week_start": {"type": "string", "description": "YYYY-MM-DD Monday, omit for current week"}},
    },
    "get_weight_history": {
        "description": "Get weight log history over the last N days.",
        "properties": {"days": {"type": "integer", "description": "default 90"}},
    },
    "get_sleep_history": {
        "description": "Get sleep log history (hours, quality) over the last N days.",
        "properties": {"days": {"type": "integer", "description": "default 30"}},
    },
    "get_medication_context": {
        "description": "Get the user's active medications, including which ones are flagged as potassium-affecting.",
        "properties": {},
    },
    "analyze_health_patterns": {
        "description": "Get exploratory cross-domain correlations (sodium vs BP, sleep vs BP, exercise vs BP, restaurant meals vs BP, weight vs BP, activity vs sleep, protein adequacy vs strength days), each with sample size and a status of insufficient_data/no_variation/computed.",
        "properties": {},
    },
    "generate_daily_plan": {
        "description": "Generate a proposed daily meal plan (breakfast/lunch/dinner/snacks) that fits the user's calorie/sodium/protein targets. Does not save anything.",
        "properties": {},
    },
}


def build_tool_specs(tool_names: list[str]) -> list[dict]:
    specs = []
    for name in tool_names:
        spec = _SPECS.get(name)
        if spec is None:
            continue
        specs.append({
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": spec["properties"],
                    "required": spec.get("required", []),
                },
            },
        })
    return specs

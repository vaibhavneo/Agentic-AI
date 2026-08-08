"""Health Orchestrator's routing logic: picks which specialist handles a
question. Deterministic keyword matching rather than an extra LLM call —
faster, free, and easy to test/audit. Order matters: more specific domains
are checked before the general fallback.
"""
from __future__ import annotations

KEYWORD_ROUTES = [
    ("health_pattern_analyst", ["pattern", "correlat", "associat", "linked to", "connection between"]),
    ("vitals_agent", ["blood pressure", " bp ", "bp?", "bp.", "bp,", "heart rate", "resting hr", "weight trend", "trend in my weight"]),
    ("fitness_agent", ["workout", "exercise", "run", "walk", "steps", "strength train", "cardio", "gym"]),
    ("heart_health_agent", ["sodium", "dash", "saturated fat", "processed food", "salt"]),
    ("food_logging_agent", ["log ", "i ate", "i just had", "find a food", "search for a food"]),
    ("nutrition_planner", ["meal plan", "what should i eat", "plan my", "protein left", "calories left", "remaining"]),
]


def route_question(message: str) -> str:
    text = message.lower()
    for specialist_key, keywords in KEYWORD_ROUTES:
        if any(kw in text for kw in keywords):
            return specialist_key
    return "general"

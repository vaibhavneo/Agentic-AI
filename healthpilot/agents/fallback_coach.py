"""Deterministic, no-AI-provider answers for the most common Coach
questions. Used when no DEEPSEEK_API_KEY/ANTHROPIC_API_KEY is configured, so
the Coach is still backed by real tool calls and real numbers rather than
going silent or showing a decorative placeholder.
"""
from __future__ import annotations

from agents.router import route_question
from agents.tool_registry import execute_tool


def answer_without_ai(profile_id: str, message: str) -> dict:
    text = message.lower()
    data_used = []

    def use(tool_name: str, args: dict | None = None):
        result = execute_tool(tool_name, profile_id, args or {})
        data_used.append({"tool": tool_name, "arguments": args or {}, "result": result})
        return result

    if "protein" in text and ("left" in text or "remaining" in text):
        remaining = use("get_remaining_nutrition_targets")
        if not remaining.get("target_set"):
            answer = "No nutrition target is set yet — visit Profile & Targets to compute one."
        else:
            p = remaining["by_nutrient"]["protein_g"]
            answer = f"You've had {p['consumed']}g of protein today against a {p['target']}g target — {p['remaining']}g remaining."
        return {"answer": answer, "specialist": "nutrition_planner", "data_used": data_used, "ai_used": False}

    # Pattern/correlation questions are checked before the narrower BP/sodium/
    # activity branches below — a question like "is there a pattern between
    # sleep and BP" mentions BP but should route to the pattern analyst, not
    # the vitals branch (matches agents/router.py's priority order).
    if any(k in text for k in ("pattern", "correlat", "associat")):
        patterns = use("analyze_health_patterns")
        computed = [a for a in patterns["associations"] if a["status"] == "computed"]
        if not computed:
            answer = "Not enough data yet for any pattern to be computed — keep logging BP, meals, sleep, and activity."
        else:
            lines = [f"{a['description']}: r={a['correlation']} (n={a['sample_size']}) — {a['caveat']}" for a in computed]
            answer = "Computed associations:\n" + "\n".join(lines)
        return {"answer": answer, "specialist": "health_pattern_analyst", "data_used": data_used, "ai_used": False}

    if "sodium" in text:
        remaining = use("get_remaining_nutrition_targets")
        if not remaining.get("target_set"):
            answer = "No nutrition target is set yet — visit Profile & Targets to compute one."
        else:
            s = remaining["by_nutrient"]["sodium_mg"]
            answer = f"You've had {s['consumed']}mg of sodium today against a {s['target']}mg ceiling — {s['remaining']}mg remaining."
        return {"answer": answer, "specialist": "heart_health_agent", "data_used": data_used, "ai_used": False}

    if "blood pressure" in text or " bp" in text:
        trend = use("calculate_bp_trend")
        avg = use("calculate_bp_average", {"days": 7})
        if avg["sample_size"] == 0:
            answer = "No BP readings logged yet — record one on the Vitals page."
        else:
            answer = (
                f"Your 7-day average BP is {avg['avg_systolic']}/{avg['avg_diastolic']} "
                f"(n={avg['sample_size']}). 30-day trend: {trend['direction']}."
            )
        return {"answer": answer, "specialist": "vitals_agent", "data_used": data_used, "ai_used": False}

    if any(k in text for k in ("workout", "exercise", "activity", "steps")):
        weekly = use("get_weekly_activity")
        answer = (
            f"This week: {weekly['moderate_minutes']} moderate + {weekly['vigorous_minutes']} vigorous aerobic minutes "
            f"({weekly['weighted_aerobic_minutes']}/150 guideline-equivalent), {weekly['strength_days']} strength day(s), "
            f"{weekly['total_steps']} steps."
        )
        return {"answer": answer, "specialist": "fitness_agent", "data_used": data_used, "ai_used": False}

    nutrition = use("get_today_nutrition")
    answer = (
        f"Today so far: {nutrition['totals']['calories_kcal']} kcal, {nutrition['totals']['protein_g']}g protein, "
        f"{nutrition['totals']['sodium_mg']}mg sodium across {nutrition['meal_count']} meal(s). "
        "No AI provider is configured, so this is a direct data lookup rather than a conversational answer — "
        "set DEEPSEEK_API_KEY in .env for free-form questions."
    )
    return {"answer": answer, "specialist": route_question(message), "data_used": data_used, "ai_used": False}

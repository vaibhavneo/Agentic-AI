"""Picks ONE concrete, real-data-backed insight for the Today page.
Deterministic (no LLM call on every page load) — priority order: a strong
computed pattern association, then a BP trend, then a weight trend, then
today's sodium budget status, then an honest 'keep logging' fallback when
there just isn't enough data yet. Never generic filler unconnected to the
profile's actual numbers.
"""
from __future__ import annotations

from insights.pattern_engine import analyze_health_patterns
from nutrition.daily_service import get_today_nutrition
from nutrition.targets import get_active_target
from vitals.bp_service import calculate_bp_trend
from vitals.weight_service import calculate_weight_trend

STRONG_CORRELATION_THRESHOLD = 0.5


def get_today_insight(profile_id: str) -> dict:
    patterns = analyze_health_patterns(profile_id)
    strong = [a for a in patterns["associations"] if a["status"] == "computed" and abs(a["correlation"]) >= STRONG_CORRELATION_THRESHOLD]
    if strong:
        best = max(strong, key=lambda a: abs(a["correlation"]))
        return {
            "text": f"{best['description']}: r={best['correlation']} over {best['sample_size']} data points. {best['caveat']}",
            "source": "pattern_analysis",
        }

    bp_trend = calculate_bp_trend(profile_id, days=30)
    if bp_trend["direction"] in ("rising", "falling") and bp_trend["sample_size"] >= 4:
        return {
            "text": (
                f"Your blood pressure has been {bp_trend['direction']} over the last 30 days "
                f"(systolic change {bp_trend['systolic_delta']:+.1f}, n={bp_trend['sample_size']})."
            ),
            "source": "bp_trend",
        }

    weight_trend = calculate_weight_trend(profile_id, days=30)
    if weight_trend["direction"] in ("rising", "falling") and weight_trend["sample_size"] >= 2:
        return {
            "text": f"Your weight has been {weight_trend['direction']} over the last 30 days ({weight_trend['delta_kg']:+.1f} kg, n={weight_trend['sample_size']}).",
            "source": "weight_trend",
        }

    target = get_active_target(profile_id)
    today = get_today_nutrition(profile_id)
    if target and today["meal_count"] > 0:
        remaining_sodium = target["sodium_mg"] - today["totals"]["sodium_mg"]
        return {
            "text": f"You have {round(remaining_sodium)}mg of sodium remaining today out of a {target['sodium_mg']}mg target.",
            "source": "today_nutrition",
        }

    return {
        "text": "Not enough data yet for a personalized insight — log a few days of meals, BP, and activity to unlock one.",
        "source": "none",
    }

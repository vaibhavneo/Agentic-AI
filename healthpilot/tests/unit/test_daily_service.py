from app.profile import create_profile
from nutrition.daily_service import calculate_daily_nutrition
from nutrition.food_service import default_serving, search_food
from nutrition.meal_service import log_food
from nutrition.water_service import log_water


def _profile():
    return create_profile(
        {
            "name": "Test", "age": 30, "sex": "female", "height_cm": 165,
            "current_weight_kg": 60, "activity_level": "light", "diet_preference": "veg",
        }
    )


def test_daily_totals_sum_across_meals():
    p = _profile()
    banana = search_food("banana", use_provider=False)[0]
    rice = search_food("white rice", use_provider=False)[0]
    log_food(p["id"], "breakfast", banana["id"], default_serving(banana)["id"], 1)
    log_food(p["id"], "lunch", rice["id"], default_serving(rice)["id"], 1)

    daily = calculate_daily_nutrition(p["id"])
    assert daily["meal_count"] == 2
    expected = round(
        89 * (default_serving(banana)["grams"] / 100.0) + 130 * (default_serving(rice)["grams"] / 100.0), 2
    )
    assert daily["totals"]["calories_kcal"] == expected


def test_daily_totals_include_water():
    p = _profile()
    log_water(p["id"], 250)
    log_water(p["id"], 300)
    daily = calculate_daily_nutrition(p["id"])
    assert daily["water_ml"] == 550


def test_daily_totals_empty_day():
    p = _profile()
    daily = calculate_daily_nutrition(p["id"], "2020-01-01")
    assert daily["meal_count"] == 0
    assert daily["totals"]["calories_kcal"] == 0
    assert daily["water_ml"] == 0

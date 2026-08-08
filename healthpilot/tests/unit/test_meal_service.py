import pytest

from app.profile import create_profile
from nutrition.food_service import default_serving, search_food
from nutrition.meal_service import (
    MealValidationError,
    add_meal_food,
    calculate_meal_nutrition,
    create_meal,
    delete_meal,
    log_food,
)


def _profile():
    return create_profile(
        {
            "name": "Test", "age": 30, "sex": "male", "height_cm": 175,
            "current_weight_kg": 75, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def test_create_meal_rejects_invalid_type():
    p = _profile()
    with pytest.raises(MealValidationError):
        create_meal(p["id"], "brunch")


def test_meal_nutrition_matches_hand_computed_value():
    p = _profile()
    food = search_food("banana", use_provider=False)[0]  # 89 kcal/100g
    serving = default_serving(food)  # 118g
    meal = create_meal(p["id"], "breakfast")
    add_meal_food(meal["id"], p["id"], food["id"], serving["id"], 1)

    totals = calculate_meal_nutrition(meal["id"], p["id"])
    expected_kcal = round(89 * (serving["grams"] / 100.0), 2)
    assert totals["calories_kcal"] == expected_kcal


def test_meal_nutrition_scales_with_quantity():
    p = _profile()
    food = search_food("banana", use_provider=False)[0]
    serving = default_serving(food)
    meal = create_meal(p["id"], "breakfast")
    add_meal_food(meal["id"], p["id"], food["id"], serving["id"], 2)

    totals = calculate_meal_nutrition(meal["id"], p["id"])
    expected_kcal = round(89 * (serving["grams"] * 2 / 100.0), 2)
    assert totals["calories_kcal"] == expected_kcal


def test_log_food_reuses_existing_meal_of_same_type_and_date():
    p = _profile()
    food = search_food("banana", use_provider=False)[0]
    serving = default_serving(food)
    meal1 = log_food(p["id"], "breakfast", food["id"], serving["id"], 1)
    meal2 = log_food(p["id"], "breakfast", food["id"], serving["id"], 1)
    assert meal1["id"] == meal2["id"]
    assert len(meal2["items"]) == 2


def test_add_meal_food_rejects_unknown_food():
    p = _profile()
    meal = create_meal(p["id"], "lunch")
    with pytest.raises(MealValidationError):
        add_meal_food(meal["id"], p["id"], 999999, None, 1)


def test_delete_meal_removes_items_via_cascade():
    p = _profile()
    food = search_food("banana", use_provider=False)[0]
    serving = default_serving(food)
    meal = log_food(p["id"], "snack", food["id"], serving["id"], 1)
    delete_meal(meal["id"], p["id"])
    with pytest.raises(MealValidationError):
        calculate_meal_nutrition(meal["id"], p["id"])

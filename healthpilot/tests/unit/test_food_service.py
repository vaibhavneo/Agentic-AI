import pytest

from nutrition.food_service import (
    FoodValidationError,
    create_manual_food,
    default_serving,
    get_food,
    resolve_serving_grams,
    search_food,
)


def test_seed_foods_are_searchable():
    results = search_food("rice", use_provider=False)
    names = {r["name"] for r in results}
    assert any("rice" in n.lower() for n in names)


def test_search_no_match_returns_empty_not_fabricated():
    results = search_food("this-food-does-not-exist-xyz", use_provider=False)
    assert results == []


def test_seed_food_has_servings():
    results = search_food("banana", use_provider=False)
    food = results[0]
    assert len(food["servings"]) >= 1
    assert any(s["is_default"] for s in food["servings"])


def test_create_manual_food_requires_positive_calories():
    with pytest.raises(FoodValidationError):
        create_manual_food({"name": "Mystery Bar", "calories_kcal": 0})


def test_create_manual_food_rejects_negative_macro():
    with pytest.raises(FoodValidationError):
        create_manual_food({"name": "Bad Food", "calories_kcal": 100, "protein_g": -5})


def test_create_manual_food_round_trip():
    food = create_manual_food(
        {
            "name": "Homemade Granola Bar",
            "calories_kcal": 210,
            "protein_g": 5,
            "carbs_g": 28,
            "sodium_mg": 60,
            "servings": [{"description": "1 bar (35g)", "grams": 35, "is_default": True}],
        }
    )
    fetched = get_food(food["id"])
    assert fetched["name"] == "Homemade Granola Bar"
    assert fetched["source"] == "manual"
    assert fetched["servings"][0]["grams"] == 35


def test_resolve_serving_grams_by_serving_id():
    food = search_food("banana", use_provider=False)[0]
    serving = default_serving(food)
    grams = resolve_serving_grams(food, serving["id"], 2)
    assert grams == serving["grams"] * 2


def test_resolve_serving_grams_direct_when_no_serving_id():
    food = search_food("banana", use_provider=False)[0]
    grams = resolve_serving_grams(food, None, 150)
    assert grams == 150


def test_resolve_serving_grams_rejects_zero_quantity():
    food = search_food("banana", use_provider=False)[0]
    serving = default_serving(food)
    with pytest.raises(FoodValidationError):
        resolve_serving_grams(food, serving["id"], 0)

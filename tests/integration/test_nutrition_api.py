import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _create_profile(client, **overrides):
    data = {
        "name": "API Test", "age": 40, "sex": "female", "height_cm": 165,
        "current_weight_kg": 65, "activity_level": "moderate", "diet_preference": "veg",
    }
    data.update(overrides)
    return client.post("/api/profiles", json=data).get_json()


def test_search_food_endpoint(client):
    resp = client.get("/api/foods/search?q=banana")
    assert resp.status_code == 200
    assert any("banana" in f["name"].lower() for f in resp.get_json())


def test_log_food_and_daily_totals_flow(client):
    profile = _create_profile(client)
    pid = profile["id"]

    food = client.get("/api/foods/search?q=banana").get_json()[0]
    serving = next(s for s in food["servings"] if s["is_default"])

    log_resp = client.post(
        f"/api/profiles/{pid}/meals/log",
        json={"meal_type": "breakfast", "food_id": food["id"], "serving_id": serving["id"], "quantity": 1},
    )
    assert log_resp.status_code == 201

    daily = client.get(f"/api/profiles/{pid}/nutrition/today").get_json()
    assert daily["meal_count"] == 1
    assert daily["totals"]["calories_kcal"] > 0


def test_log_food_text_endpoint(client):
    profile = _create_profile(client)
    pid = profile["id"]
    resp = client.post(
        f"/api/profiles/{pid}/meals/log_text", json={"meal_type": "lunch", "text": "banana"}
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert len(body["logged"]) == 1


def test_targets_recompute_and_remaining_flow(client):
    profile = _create_profile(client)
    pid = profile["id"]

    recompute = client.post(f"/api/profiles/{pid}/nutrition/targets/recompute", json={})
    assert recompute.status_code == 201
    target = recompute.get_json()
    assert target["calories"] > 0

    food = client.get("/api/foods/search?q=banana").get_json()[0]
    serving = next(s for s in food["servings"] if s["is_default"])
    client.post(
        f"/api/profiles/{pid}/meals/log",
        json={"meal_type": "breakfast", "food_id": food["id"], "serving_id": serving["id"], "quantity": 1},
    )

    remaining = client.get(f"/api/profiles/{pid}/nutrition/remaining").get_json()
    assert remaining["target_set"] is True
    assert remaining["by_nutrient"]["calories"]["consumed"] > 0
    assert remaining["by_nutrient"]["calories"]["remaining"] < target["calories"]


def test_water_logging_flow(client):
    profile = _create_profile(client)
    pid = profile["id"]
    client.post(f"/api/profiles/{pid}/water", json={"amount_ml": 300})
    resp = client.get(f"/api/profiles/{pid}/water/today")
    assert resp.get_json()["amount_ml"] == 300


def test_delete_meal_removes_it_from_daily_totals(client):
    profile = _create_profile(client)
    pid = profile["id"]
    food = client.get("/api/foods/search?q=banana").get_json()[0]
    serving = next(s for s in food["servings"] if s["is_default"])
    meal = client.post(
        f"/api/profiles/{pid}/meals/log",
        json={"meal_type": "snack", "food_id": food["id"], "serving_id": serving["id"], "quantity": 1},
    ).get_json()

    client.delete(f"/api/profiles/{pid}/meals/{meal['id']}")
    daily = client.get(f"/api/profiles/{pid}/nutrition/today").get_json()
    assert daily["meal_count"] == 0


def test_create_manual_food_via_api(client):
    resp = client.post(
        "/api/foods",
        json={"name": "Homemade Smoothie", "calories_kcal": 180, "protein_g": 6},
    )
    assert resp.status_code == 201
    assert resp.get_json()["name"] == "Homemade Smoothie"


def test_meals_page_redirects_without_active_profile(client):
    resp = client.get("/meals")
    assert resp.status_code == 302


def test_meals_page_renders_with_active_profile(client):
    _create_profile(client)
    resp = client.get("/meals")
    assert resp.status_code == 200

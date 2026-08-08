import datetime as dt

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _profile(client, **overrides):
    data = {
        "name": "Plan API Test", "age": 36, "sex": "female", "height_cm": 167,
        "current_weight_kg": 63, "activity_level": "moderate", "diet_preference": "veg",
        "meals_per_day": 3,
    }
    data.update(overrides)
    return client.post("/api/profiles", json=data).get_json()


def _monday():
    today = dt.date.today()
    return (today - dt.timedelta(days=today.weekday())).isoformat()


def test_create_and_get_weekly_plan(client):
    p = _profile(client)
    create_resp = client.post(f"/api/profiles/{p['id']}/weekly-plan", json={"week_start": _monday()})
    assert create_resp.status_code == 201
    plan = create_resp.get_json()
    assert len(plan["days"]) == 7

    get_resp = client.get(f"/api/profiles/{p['id']}/weekly-plan?week_start={_monday()}")
    assert get_resp.status_code == 200


def test_create_weekly_plan_with_malformed_week_start_returns_400(client):
    p = _profile(client)
    resp = client.post(f"/api/profiles/{p['id']}/weekly-plan", json={"week_start": "not-a-date"})
    assert resp.status_code == 400


def test_weekly_plan_page_with_malformed_week_start_does_not_500(client):
    _profile(client)
    resp = client.get("/weekly-plan?week_start=not-a-date")
    assert resp.status_code == 302  # redirects to the current week instead of crashing


def test_get_missing_plan_returns_404(client):
    p = _profile(client)
    resp = client.get(f"/api/profiles/{p['id']}/weekly-plan?week_start={_monday()}")
    assert resp.status_code == 404


def test_swap_lock_and_source_flow(client):
    p = _profile(client)
    plan = client.post(f"/api/profiles/{p['id']}/weekly-plan", json={"week_start": _monday()}).get_json()
    meal_id = plan["days"][0]["meals"][0]["id"]

    lock_resp = client.post(f"/api/profiles/{p['id']}/plan-meals/{meal_id}/lock", json={"locked": True})
    assert lock_resp.get_json()["locked"] == 1

    swap_resp = client.post(f"/api/profiles/{p['id']}/plan-meals/{meal_id}/swap", json={})
    assert swap_resp.status_code == 400  # locked meals can't be swapped

    client.post(f"/api/profiles/{p['id']}/plan-meals/{meal_id}/lock", json={"locked": False})
    swap_resp2 = client.post(f"/api/profiles/{p['id']}/plan-meals/{meal_id}/swap", json={})
    assert swap_resp2.status_code == 200

    source_resp = client.post(f"/api/profiles/{p['id']}/plan-meals/{meal_id}/source", json={"source": "restaurant"})
    assert source_resp.get_json()["items"] == []


def test_grocery_list_endpoint(client):
    p = _profile(client)
    client.post(f"/api/profiles/{p['id']}/weekly-plan", json={"week_start": _monday()})
    resp = client.get(f"/api/profiles/{p['id']}/grocery-list?week_start={_monday()}")
    assert resp.status_code == 200
    assert "by_category" in resp.get_json()


def test_weekly_plan_page_shows_generate_button_when_no_plan(client):
    _profile(client)
    resp = client.get("/weekly-plan")
    assert resp.status_code == 200
    assert b"Generate Weekly Plan" in resp.data


def test_weekly_plan_page_shows_plan_when_exists(client):
    p = _profile(client)
    client.post(f"/api/profiles/{p['id']}/weekly-plan", json={"week_start": _monday()})
    resp = client.get(f"/weekly-plan?week_start={_monday()}")
    assert resp.status_code == 200
    assert b"Grocery List" in resp.data

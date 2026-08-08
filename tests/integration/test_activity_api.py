import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _profile(client):
    return client.post(
        "/api/profiles",
        json={
            "name": "Activity Test", "age": 33, "sex": "female", "height_cm": 168,
            "current_weight_kg": 62, "activity_level": "active", "diet_preference": "veg",
        },
    ).get_json()


def test_log_cardio_workout_via_api(client):
    p = _profile(client)
    resp = client.post(
        f"/api/profiles/{p['id']}/workouts",
        json={"workout_type": "cardio", "activity": "running", "duration_min": 30, "intensity": "vigorous", "distance_km": 5},
    )
    assert resp.status_code == 201
    assert resp.get_json()["intensity"] == "vigorous"


def test_log_cardio_without_intensity_returns_400(client):
    p = _profile(client)
    resp = client.post(
        f"/api/profiles/{p['id']}/workouts",
        json={"workout_type": "cardio", "activity": "running", "duration_min": 30},
    )
    assert resp.status_code == 400


def test_log_strength_workout_with_sets_via_api(client):
    p = _profile(client)
    resp = client.post(
        f"/api/profiles/{p['id']}/workouts",
        json={
            "workout_type": "strength", "activity": "gym", "duration_min": 50,
            "strength_sets": [{"exercise_name": "Bench Press", "reps": 5, "weight_kg": 60}],
        },
    )
    assert resp.status_code == 201
    assert len(resp.get_json()["sets"]) == 1


def test_today_and_weekly_activity_endpoints(client):
    p = _profile(client)
    client.post(
        f"/api/profiles/{p['id']}/workouts",
        json={"workout_type": "cardio", "activity": "walking", "duration_min": 25, "intensity": "moderate", "steps": 3000},
    )
    today = client.get(f"/api/profiles/{p['id']}/activity/today").get_json()
    assert today["workout_count"] == 1
    assert today["total_steps"] == 3000

    weekly = client.get(f"/api/profiles/{p['id']}/activity/weekly").get_json()
    assert weekly["moderate_minutes"] == 25


def test_delete_workout_via_api(client):
    p = _profile(client)
    workout = client.post(
        f"/api/profiles/{p['id']}/workouts",
        json={"workout_type": "cardio", "activity": "cycling", "duration_min": 40, "intensity": "moderate"},
    ).get_json()
    del_resp = client.delete(f"/api/profiles/{p['id']}/workouts/{workout['id']}")
    assert del_resp.status_code == 200
    today = client.get(f"/api/profiles/{p['id']}/activity/today").get_json()
    assert today["workout_count"] == 0


def test_activity_page_redirects_without_active_profile(client):
    resp = client.get("/activity")
    assert resp.status_code == 302


def test_activity_page_renders_with_active_profile(client):
    _profile(client)
    resp = client.get("/activity")
    assert resp.status_code == 200
    assert b"Log a workout" in resp.data

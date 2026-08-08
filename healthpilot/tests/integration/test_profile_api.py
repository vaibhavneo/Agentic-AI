import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _payload(**overrides):
    data = {
        "name": "Nina",
        "age": 38,
        "sex": "female",
        "height_cm": 165,
        "current_weight_kg": 70,
        "activity_level": "moderate",
        "diet_preference": "veg",
        "meals_per_day": 3,
        "allergies": ["peanuts"],
    }
    data.update(overrides)
    return data


def test_create_profile_via_api(client):
    resp = client.post("/api/profiles", json=_payload())
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Nina"
    assert body["allergies"] == ["peanuts"]


def test_create_profile_invalid_returns_400(client):
    resp = client.post("/api/profiles", json=_payload(age=999))
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_get_profile_not_found(client):
    resp = client.get("/api/profiles/does-not-exist")
    assert resp.status_code == 404


def test_full_profile_and_medication_flow(client):
    profile = client.post("/api/profiles", json=_payload()).get_json()
    pid = profile["id"]

    med_resp = client.post(
        f"/api/profiles/{pid}/medications",
        json={"name": "Valsartan", "dose": "80mg", "frequency": "once daily"},
    )
    assert med_resp.status_code == 201
    med = med_resp.get_json()
    assert med["potassium_risk"] == 1

    log_resp = client.post(
        f"/api/profiles/{pid}/medications/{med['id']}/log", json={"taken": True}
    )
    assert log_resp.status_code == 201

    list_resp = client.get(f"/api/profiles/{pid}/medications")
    assert len(list_resp.get_json()) == 1


def test_profile_page_renders(client):
    resp = client.get("/profile")
    assert resp.status_code == 200
    assert b"Create Profile" in resp.data or b"Edit Profile" in resp.data


def test_profile_page_has_four_sections(client):
    resp = client.get("/profile")
    assert b"Basics" in resp.data
    assert b"Goals" in resp.data and b"Diet" in resp.data
    assert b"Health" in resp.data and b"Safety" in resp.data
    assert b"Daily Routine" in resp.data
    assert b"Metric" in resp.data  # unit toggle present


def test_profile_page_uses_polished_labels_not_raw_enums(client):
    resp = client.get("/profile")
    assert b"Vegetarian" in resp.data
    assert b"Sedentary / mostly seated" in resp.data
    assert b">veg<" not in resp.data
    assert b">sedentary<" not in resp.data


def test_create_profile_with_health_goals_and_exercise_limitations(client):
    resp = client.post(
        "/api/profiles",
        json=_payload(primary_health_goals="Lower blood pressure", exercise_limitations="Bad knee"),
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["primary_health_goals"] == "Lower blood pressure"
    assert body["exercise_limitations"] == "Bad knee"

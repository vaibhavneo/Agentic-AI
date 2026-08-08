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
            "name": "Vitals Test", "age": 58, "sex": "male", "height_cm": 172,
            "current_weight_kg": 88, "activity_level": "sedentary", "diet_preference": "non_veg",
        },
    ).get_json()


def test_record_bp_normal_via_api(client):
    p = _profile(client)
    resp = client.post(f"/api/profiles/{p['id']}/vitals/bp", json={"systolic_1": 115, "diastolic_1": 75})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["category"] == "normal"
    assert body["urgency"] == "info"
    assert body["emergency"] == 0


def test_record_bp_crisis_with_symptom_flags_emergency_via_api(client):
    p = _profile(client)
    resp = client.post(
        f"/api/profiles/{p['id']}/vitals/bp",
        json={"systolic_1": 195, "diastolic_1": 128, "symptoms": ["chest_pain"]},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["category"] == "crisis"
    assert body["emergency"] == 1
    assert "emergency" in body["message"].lower()


def test_record_bp_invalid_symptom_returns_400(client):
    p = _profile(client)
    resp = client.post(
        f"/api/profiles/{p['id']}/vitals/bp",
        json={"systolic_1": 120, "diastolic_1": 80, "symptoms": ["not_a_real_symptom"]},
    )
    assert resp.status_code == 400


def test_bp_average_and_trend_endpoints(client):
    p = _profile(client)
    client.post(f"/api/profiles/{p['id']}/vitals/bp", json={"systolic_1": 118, "diastolic_1": 76})
    client.post(f"/api/profiles/{p['id']}/vitals/bp", json={"systolic_1": 122, "diastolic_1": 78})

    avg = client.get(f"/api/profiles/{p['id']}/vitals/bp/average?days=7").get_json()
    assert avg["sample_size"] == 2

    trend = client.get(f"/api/profiles/{p['id']}/vitals/bp/trend?days=30").get_json()
    assert trend["sample_size"] == 2


def test_weight_and_sleep_endpoints(client):
    p = _profile(client)
    w = client.post(f"/api/profiles/{p['id']}/vitals/weight", json={"weight_kg": 87.5})
    assert w.status_code == 201
    history = client.get(f"/api/profiles/{p['id']}/vitals/weight").get_json()
    assert len(history) == 1

    s = client.post(f"/api/profiles/{p['id']}/vitals/sleep", json={"hours": 6.5, "quality": 3})
    assert s.status_code == 201
    sleep_history = client.get(f"/api/profiles/{p['id']}/vitals/sleep").get_json()
    assert sleep_history[0]["hours"] == 6.5


def test_vitals_page_redirects_without_active_profile(client):
    resp = client.get("/vitals")
    assert resp.status_code == 302


def test_vitals_page_renders_with_active_profile(client):
    _profile(client)
    resp = client.get("/vitals")
    assert resp.status_code == 200
    assert b"Record Blood Pressure" in resp.data


def test_other_vitals_endpoint(client):
    p = _profile(client)
    resp = client.post(f"/api/profiles/{p['id']}/vitals/other", json={"resting_hr": 58, "spo2_pct": 98})
    assert resp.status_code == 201
    history = client.get(f"/api/profiles/{p['id']}/vitals/other").get_json()
    assert history[0]["resting_hr"] == 58

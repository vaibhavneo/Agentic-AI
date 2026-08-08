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
            "name": "Today Test", "age": 31, "sex": "female", "height_cm": 164,
            "current_weight_kg": 60, "activity_level": "moderate", "diet_preference": "veg",
        },
    ).get_json()


def test_today_redirects_without_active_profile(client):
    resp = client.get("/today")
    assert resp.status_code == 302


def test_today_renders_with_active_profile(client):
    _profile(client)
    resp = client.get("/today")
    assert resp.status_code == 200
    assert b"Health Score" in resp.data
    assert b"Today's Insight" in resp.data
    assert b"Quick Actions" in resp.data
    assert b"Medication" in resp.data
    assert b"Morning Health" in resp.data


def test_today_quick_actions_link_to_real_pages(client):
    _profile(client)
    resp = client.get("/today")
    assert b'href="/meals"' in resp.data
    assert b'href="/vitals"' in resp.data
    assert b'href="/activity"' in resp.data
    assert b'href="/coach"' in resp.data


def test_today_medication_section_shows_taken_status(client):
    p = _profile(client)
    med = client.post(f"/api/profiles/{p['id']}/medications", json={"name": "Losartan"}).get_json()
    client.post(f"/api/profiles/{p['id']}/medications/{med['id']}/log", json={"taken": True})
    resp = client.get("/today")
    assert b"Losartan" in resp.data
    assert b"taken" in resp.data


def test_index_redirects_to_today_when_profile_active(client):
    _profile(client)
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/today" in resp.headers["Location"]


def test_index_redirects_to_profile_when_no_active_profile(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/profile" in resp.headers["Location"]


def test_today_page_after_logging_shows_real_data(client):
    p = _profile(client)
    client.post(f"/api/profiles/{p['id']}/nutrition/targets/recompute", json={})
    food = client.get("/api/foods/search?q=banana").get_json()[0]
    serving = next(s for s in food["servings"] if s["is_default"])
    client.post(
        f"/api/profiles/{p['id']}/meals/log",
        json={"meal_type": "breakfast", "food_id": food["id"], "serving_id": serving["id"], "quantity": 1},
    )
    resp = client.get("/today")
    assert resp.status_code == 200
    assert b"Banana" in resp.data

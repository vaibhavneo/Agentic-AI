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
            "name": "Coach Test", "age": 39, "sex": "male", "height_cm": 177,
            "current_weight_kg": 81, "activity_level": "moderate", "diet_preference": "veg",
        },
    ).get_json()


def test_coach_ask_requires_message(client):
    p = _profile(client)
    resp = client.post(f"/api/profiles/{p['id']}/coach/ask", json={"message": ""})
    assert resp.status_code == 400


def test_coach_ask_returns_data_grounded_answer_without_ai_key(client):
    p = _profile(client)
    resp = client.post(f"/api/profiles/{p['id']}/coach/ask", json={"message": "how much protein do I have left"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ai_used"] is False
    assert "data_used" in body
    assert len(body["data_used"]) >= 1


def test_insights_endpoint_returns_seven_associations(client):
    p = _profile(client)
    resp = client.get(f"/api/profiles/{p['id']}/insights")
    assert resp.status_code == 200
    assert len(resp.get_json()["associations"]) == 7


def test_coach_page_redirects_without_active_profile(client):
    resp = client.get("/coach")
    assert resp.status_code == 302


def test_coach_page_renders_with_active_profile(client):
    _profile(client)
    resp = client.get("/coach")
    assert resp.status_code == 200
    assert b"AI Health Coach" in resp.data


def test_coach_page_redirects_when_session_profile_no_longer_exists(client):
    """Regression test: a session can reference a profile_id that no longer
    exists (profile deleted elsewhere, or the database was reset out from
    under a live session) — the page route must redirect to Profile &
    Targets rather than rendering a broken chat UI."""
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "does-not-exist-anymore"
    resp = client.get("/coach")
    assert resp.status_code == 302
    assert "/profile" in resp.headers["Location"]


def test_coach_ask_with_nonexistent_profile_returns_structured_404(client):
    """Documents the API contract coach.js relies on: a stale/nonexistent
    profile_id (e.g. baked into a page that was loaded before the profile
    was deleted) must come back as a clean 404 with a machine-readable
    error, never a 500 or an unstructured response — see coach.js's
    res.status === 404 check, which turns this into a friendly chat message
    instead of surfacing "no such profile" verbatim."""
    resp = client.post(
        "/api/profiles/does-not-exist-anymore/coach/ask", json={"message": "how am I doing?"}
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "no such profile"


def test_coach_ask_dinner_question_grounds_in_real_data(client):
    """The exact question that surfaced the original bug report. With no AI
    key configured, the fallback path still must answer from real stored
    data (not fabricate nutrition facts about foods that aren't in the
    database) and must return 200, not the raw profile-lookup error."""
    p = _profile(client)
    client.post(f"/api/profiles/{p['id']}/nutrition/targets/recompute", json={})
    resp = client.post(
        f"/api/profiles/{p['id']}/coach/ask",
        json={"message": "Should I eat 2 makke roti and sarson ka saag for dinner"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "error" not in body
    assert len(body["data_used"]) >= 1
    # every data_used entry must trace back to a real tool call, not a fabricated one
    for entry in body["data_used"]:
        assert "tool" in entry and "result" in entry


def test_insights_page_renders(client):
    _profile(client)
    resp = client.get("/insights")
    assert resp.status_code == 200
    assert b"Not enough data yet" in resp.data

"""Multi-profile isolation is the core privacy guarantee of a local-first,
multi-user app: nothing scoped to profile A should ever be readable, listable,
or mutable through profile B's id.
"""
import pytest

from app.medication import create_medication, get_medication, list_medications
from app.profile import create_profile, delete_profile, get_profile
from database.db import get_connection
from safety.events import list_safety_events, log_safety_event
from web.app import create_app


def _profile(name):
    return create_profile(
        {
            "name": name, "age": 40, "sex": "other", "height_cm": 170,
            "current_weight_kg": 70, "activity_level": "moderate", "diet_preference": "veg",
        }
    )


def test_medication_not_visible_across_profiles():
    a, b = _profile("A"), _profile("B")
    med = create_medication(a["id"], {"name": "Lisinopril"})

    assert get_medication(med["id"], b["id"]) is None
    assert med["id"] not in [m["id"] for m in list_medications(b["id"])]


def test_deleting_profile_cascades_and_does_not_affect_other_profile():
    a, b = _profile("A"), _profile("B")
    create_medication(a["id"], {"name": "Lisinopril"})
    create_medication(b["id"], {"name": "Metformin"})

    delete_profile(a["id"])

    assert get_profile(a["id"]) is None
    assert list_medications(a["id"]) == []
    assert get_profile(b["id"]) is not None
    assert len(list_medications(b["id"])) == 1

    conn = get_connection()
    orphaned = conn.execute(
        "SELECT COUNT(*) c FROM medications WHERE profile_id = ?", (a["id"],)
    ).fetchone()["c"]
    assert orphaned == 0


def test_safety_events_scoped_per_profile():
    a, b = _profile("A"), _profile("B")
    log_safety_event(a["id"], "test_event", "info", "hello A")
    assert list_safety_events(a["id"]) != []
    assert list_safety_events(b["id"]) == []


def test_api_cannot_update_medication_via_wrong_profile_id():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        a = client.post(
            "/api/profiles",
            json={
                "name": "A", "age": 40, "sex": "other", "height_cm": 170,
                "current_weight_kg": 70, "activity_level": "moderate", "diet_preference": "veg",
            },
        ).get_json()
        b = client.post(
            "/api/profiles",
            json={
                "name": "B", "age": 40, "sex": "other", "height_cm": 170,
                "current_weight_kg": 70, "activity_level": "moderate", "diet_preference": "veg",
            },
        ).get_json()
        med = client.post(
            f"/api/profiles/{a['id']}/medications", json={"name": "Lisinopril"}
        ).get_json()

        # Attempting to reach A's medication through B's profile id must fail.
        resp = client.put(
            f"/api/profiles/{b['id']}/medications/{med['id']}", json={"name": "Hacked"}
        )
        assert resp.status_code == 400  # ValidationError: no such medication for this profile

        still_a = get_medication(med["id"], a["id"])
        assert still_a["name"] == "Lisinopril"

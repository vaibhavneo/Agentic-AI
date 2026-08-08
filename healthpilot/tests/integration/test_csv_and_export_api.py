import io
import json

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
            "name": "CSV API Test", "age": 42, "sex": "male", "height_cm": 174,
            "current_weight_kg": 79, "activity_level": "moderate", "diet_preference": "veg",
        },
    ).get_json()


def test_csv_template_download(client):
    resp = client.get("/api/csv-templates/bp")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert b"systolic_1" in resp.data


def test_csv_template_unknown_kind_404s(client):
    resp = client.get("/api/csv-templates/not-a-kind")
    assert resp.status_code == 404


def test_csv_import_endpoint(client):
    p = _profile(client)
    csv_bytes = b"date,weight_kg,notes\n2026-01-01,70.5,\n"
    resp = client.post(
        f"/api/profiles/{p['id']}/import/weight",
        data={"file": (io.BytesIO(csv_bytes), "weights.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["imported"] == 1


def test_csv_import_missing_file_returns_400(client):
    p = _profile(client)
    resp = client.post(f"/api/profiles/{p['id']}/import/weight", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_csv_import_unknown_kind_404s(client):
    p = _profile(client)
    resp = client.post(
        f"/api/profiles/{p['id']}/import/not-a-kind",
        data={"file": (io.BytesIO(b"x"), "x.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 404


def test_export_endpoint_returns_full_json(client):
    p = _profile(client)
    client.post(f"/api/profiles/{p['id']}/vitals/weight", json={"weight_kg": 79.5})
    resp = client.get(f"/api/profiles/{p['id']}/export")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert "attachment" in resp.headers["Content-Disposition"]
    data = json.loads(resp.data)
    assert data["profile"]["id"] == p["id"]
    assert len(data["weight_logs"]) == 1


def test_delete_via_api_removes_profile(client):
    p = _profile(client)
    resp = client.delete(f"/api/profiles/{p['id']}")
    assert resp.status_code == 200
    assert client.get(f"/api/profiles/{p['id']}").status_code == 404

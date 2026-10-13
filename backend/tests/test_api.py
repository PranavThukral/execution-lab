from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_separate_frontend_backend_is_ready_without_local_build(monkeypatch):
    exists = Path.exists
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FRONTEND_EXTERNAL", "true")
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: False if path.name == "index.html" else exists(path),
    )
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["frontend"] is False
    assert response.json()["bars"] == 2340
    assert client.post("/api/v1/simulations", json={}).status_code == 200


def test_single_service_production_requires_its_frontend_build(monkeypatch):
    exists = Path.exists
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("FRONTEND_EXTERNAL", raising=False)
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: False if path.name == "index.html" else exists(path),
    )
    response = client.get("/readyz")
    assert response.status_code == 503
    assert "Frontend build" in response.json()["error"]["message"]


def test_ready_and_simulation():
    assert client.get("/readyz").status_code == 200
    response = client.post("/api/v1/simulations", json={})
    assert response.status_code == 200
    body = response.json()
    assert len(body["strategies"]) == 3
    assert body["dataset"]["data_kind"] == "synthetic"


def test_bad_window_is_readable():
    response = client.post(
        "/api/v1/simulations", json={"start": "2025-06-09T10:00:00", "end": "2025-06-09T11:00:00"}
    )
    assert response.status_code in (400, 422)


def test_full_regular_session_and_consistent_error_shape():
    response = client.post(
        "/api/v1/simulations",
        json={"start": "2025-06-09T09:30:00-04:00", "end": "2025-06-09T16:00:00-04:00"},
    )
    assert response.status_code == 200
    assert len(response.json()["market"]) == 390
    invalid = client.post("/api/v1/simulations", json={"quantity": 0})
    assert invalid.status_code == 422
    assert set(invalid.json()["error"]) >= {"code", "message", "fields", "request_id"}


def test_calendar_rejects_holiday_and_unknown_session_is_not_empty_success():
    holiday = client.post(
        "/api/v1/simulations",
        json={"start": "2025-07-04T09:30:00-04:00", "end": "2025-07-04T10:00:00-04:00"},
    )
    assert holiday.status_code == 422
    missing = client.get("/api/v1/datasets/demo-sim-v1/bars", params={"session": "2025-07-04"})
    assert missing.status_code == 404

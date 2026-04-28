from fastapi.testclient import TestClient

from api.main import app


def test_missing_api_key_returns_401(monkeypatch) -> None:
    monkeypatch.setenv("API_KEYS", "test-api-key-for-ci:read-write")
    client = TestClient(app)

    response = client.get("/api/v1/status/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 401


def test_invalid_api_key_returns_401(monkeypatch) -> None:
    monkeypatch.setenv("API_KEYS", "test-api-key-for-ci:read-write")
    client = TestClient(app)

    response = client.get(
        "/api/v1/status/00000000-0000-0000-0000-000000000000",
        headers={"X-API-Key": "wrong"},
    )

    assert response.status_code == 401


def test_read_only_key_cannot_submit_application(monkeypatch, sample_apply_payload) -> None:
    monkeypatch.setenv("API_KEYS", "test-api-key-for-ci:read")
    client = TestClient(app)

    response = client.post(
        "/api/v1/apply-loan",
        json=sample_apply_payload,
        headers={"X-API-Key": "test-api-key-for-ci"},
    )

    assert response.status_code == 403


def test_health_no_auth_required() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200


def test_metrics_no_auth_required() -> None:
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200

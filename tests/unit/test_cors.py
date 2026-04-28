import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.main import configure_cors, cors_allowed_origins


def test_cors_restricted_to_configured_origins(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://portal.auditlend.example")
    app = FastAPI()
    configure_cors(app)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    client = TestClient(app)

    allowed = client.options(
        "/ok",
        headers={
            "Origin": "https://portal.auditlend.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    blocked = client.options(
        "/ok",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://portal.auditlend.example"
    assert blocked.status_code == 400
    assert "access-control-allow-origin" not in blocked.headers


def test_wildcard_cors_origin_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")

    with pytest.raises(RuntimeError):
        cors_allowed_origins()

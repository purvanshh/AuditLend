from fastapi.testclient import TestClient

from mock_apis.bank_analyzer import app as bank_app
from mock_apis.credit_bureau import app as credit_app
from mock_apis.gst_verifier import app as gst_app


PAN = "AAAAA1111A"


def test_credit_bureau_success_is_deterministic_for_pan() -> None:
    client = TestClient(credit_app)

    first = client.get("/credit-score", params={"pan": PAN, "fail_mode": "SUCCESS"})
    second = client.get("/credit-score", params={"pan": PAN, "fail_mode": "SUCCESS"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["credit_score"] == second.json()["credit_score"]
    assert first.json()["last_updated"] == "2026-04-01T00:00:00Z"


def test_credit_bureau_service_down_returns_exact_error_body() -> None:
    client = TestClient(credit_app)

    response = client.get("/credit-score", params={"pan": PAN, "fail_mode": "SERVICE_DOWN"})

    assert response.status_code == 503
    assert response.json()["error"] == "Service unavailable"
    assert response.json()["request_id"].startswith("credit_")


def test_bank_analyzer_partial_data_omits_expected_fields() -> None:
    client = TestClient(bank_app)

    response = client.post(
        "/analyze",
        params={"fail_mode": "PARTIAL_DATA"},
        json={"pan": PAN, "bank_statement": []},
    )

    payload = response.json()
    assert response.status_code == 200
    assert "average_balance" not in payload
    assert "income_stability" not in payload
    assert payload["request_id"].startswith("bank_")


def test_bank_analyzer_format_error_returns_exact_error_body() -> None:
    client = TestClient(bank_app)

    response = client.post(
        "/analyze",
        params={"fail_mode": "FORMAT_ERROR"},
        json={"pan": PAN, "bank_statement": []},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Unable to parse bank statement"


def test_gst_pan_mismatch_is_typed_successful_response() -> None:
    client = TestClient(gst_app)

    response = client.get("/verify-gst", params={"pan": PAN, "fail_mode": "PAN_MISMATCH"})

    assert response.status_code == 200
    assert response.json()["match"] is False
    assert response.json()["request_id"].startswith("gst_")


def test_gst_no_record_returns_exact_error_body() -> None:
    client = TestClient(gst_app)

    response = client.get("/verify-gst", params={"pan": PAN, "fail_mode": "NO_RECORD"})

    assert response.status_code == 404
    assert response.json()["error"] == "No GST record found for this PAN"

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from api.dependencies import get_async_session
from api.main import app
from api.schemas.application import ApplyLoanRequest


VALID_PAYLOAD = {
    "idempotency_key": "validation-001",
    "user_data": {
        "name": "Jane Doe",
        "pan": "ABCDE1234F",
        "monthly_income": 120000,
        "existing_emis": 25000,
        "loan_amount": 500000,
        "tenure_months": 36,
    },
}


async def _unused_session_override():
    yield None


def _post_apply_loan_without_db(payload: dict):
    app.dependency_overrides[get_async_session] = _unused_session_override
    try:
        return TestClient(app).post("/api/v1/apply-loan", json=payload)
    finally:
        app.dependency_overrides.pop(get_async_session, None)


def test_api_rejects_gst_timeout_failure_flag_before_route_execution() -> None:
    response = _post_apply_loan_without_db(
        {
            **VALID_PAYLOAD,
            "failure_flags": {"gst_verifier": "TIMEOUT"},
        },
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "gst_verifier" in response.json()["detail"]


def test_api_rejects_credit_pan_mismatch_failure_flag_before_route_execution() -> None:
    response = _post_apply_loan_without_db(
        {
            **VALID_PAYLOAD,
            "failure_flags": {"credit_bureau": "PAN_MISMATCH"},
        },
    )

    assert response.status_code == 400
    assert "credit_bureau" in response.json()["detail"]


def test_apply_request_model_accepts_valid_per_service_failure_modes() -> None:
    request = ApplyLoanRequest.model_validate(
        {
            **VALID_PAYLOAD,
            "failure_flags": {
                "credit_bureau": "TIMEOUT",
                "bank_analyzer": "PARTIAL_DATA",
                "gst_verifier": "PAN_MISMATCH",
            },
        }
    )

    assert request.failure_flags is not None
    assert request.failure_flags.credit_bureau == "TIMEOUT"
    assert request.failure_flags.bank_analyzer == "PARTIAL_DATA"
    assert request.failure_flags.gst_verifier == "PAN_MISMATCH"


def test_apply_request_model_rejects_invalid_cross_service_failure_modes() -> None:
    with pytest.raises(ValidationError):
        ApplyLoanRequest.model_validate(
            {
                **VALID_PAYLOAD,
                "failure_flags": {
                    "credit_bureau": "NO_RECORD",
                    "bank_analyzer": "SERVICE_DOWN",
                    "gst_verifier": "FORMAT_ERROR",
                },
            }
        )

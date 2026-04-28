import asyncio

from prometheus_client import generate_latest
from sqlalchemy import text

from services import FailureType, ServiceResult
from worker.tasks import process_application as task_module


class FakeRedis:
    async def aclose(self) -> None:
        return None


def test_full_remediated_pipeline(api_client, clean_database, sample_apply_payload, monkeypatch) -> None:
    """
    End-to-end test that verifies all remediation fixes work together:
    risk scoring, calibrated confidence, encrypted PII, idempotency,
    audit trail, metrics, and explanation output.
    """
    payload = {
        **sample_apply_payload,
        "idempotency_key": "remediation-verification-001",
        "failure_flags": {
            "credit_bureau": "STALE_DATA",
            "bank_analyzer": "PARTIAL_DATA",
            "gst_verifier": "SUCCESS",
        },
    }

    first = api_client.post("/api/v1/apply-loan", json=payload)
    second = api_client.post("/api/v1/apply-loan", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    application_id = first.json()["application_id"]
    assert second.json()["application_id"] == application_id

    async def fake_fetch_external_data(app_id, user_data, failure_flags, redis_client):
        assert user_data["pan"] == payload["user_data"]["pan"]
        return (
            ServiceResult(
                success=False,
                data={
                    "pan": payload["user_data"]["pan"],
                    "credit_score": 850,
                    "last_updated": "2025-07-15T00:00:00Z",
                },
                failure_type=FailureType.STALE_DATA,
                raw_response={
                    "pan": payload["user_data"]["pan"],
                    "credit_score": 850,
                    "last_updated": "2025-07-15T00:00:00Z",
                },
            ),
            ServiceResult(
                success=False,
                data={"monthly_inflow": 120000, "monthly_outflow": 65000},
                failure_type=FailureType.PARTIAL_DATA,
                raw_response={"monthly_inflow": 120000, "monthly_outflow": 65000},
            ),
            ServiceResult(
                success=True,
                data={"gst_compliant": True},
                raw_response={"gst_compliant": True},
            ),
        )

    monkeypatch.setattr(task_module.redis_async, "from_url", lambda *args, **kwargs: FakeRedis())
    monkeypatch.setattr(task_module, "_fetch_external_data", fake_fetch_external_data)

    worker_result = asyncio.run(task_module._process_application(application_id))

    assert worker_result["status"] == "MANUAL_REVIEW"
    assert worker_result["decision"] == "NEEDS_REVIEW"
    assert worker_result["risk_score"] > 70
    assert worker_result["data_reliability"] == 0.6
    assert worker_result["confidence"] == 0.54
    assert worker_result["confidence"] != worker_result["data_reliability"]

    decision = api_client.get(f"/api/v1/decision/{application_id}")
    assert decision.status_code == 200
    decision_body = decision.json()
    assert decision_body["risk_score"] == worker_result["risk_score"]
    assert decision_body["data_reliability"] == worker_result["data_reliability"]
    assert any("risk_score (computed)" in factor for factor in decision_body["factors"])

    explanation = api_client.get(f"/api/v1/explanation/{application_id}")
    assert explanation.status_code == 200
    explanation_body = explanation.json()
    assert explanation_body["decision"] == "NEEDS_REVIEW"
    assert any(factor["name"] == "Risk Score" for factor in explanation_body["factors"])

    raw_pan = payload["user_data"]["pan"]
    with clean_database.connect() as connection:
        pii_row = connection.execute(
            text(
                "SELECT pan_hash, encrypted_user_data IS NOT NULL AS has_ciphertext, "
                "encryption_nonce IS NOT NULL AS has_nonce "
                "FROM loan_applications WHERE id = :id"
            ),
            {"id": application_id},
        ).one()
        audit_count = connection.scalar(
            text("SELECT count(*) FROM audit_logs WHERE application_id = :id"),
            {"id": application_id},
        )
        audit_text = connection.scalar(
            text(
                "SELECT coalesce(string_agg(coalesce(input_snapshot::text, '') || coalesce(output_snapshot::text, ''), ' '), '') "
                "FROM audit_logs WHERE application_id = :id"
            ),
            {"id": application_id},
        )
        external_text = connection.scalar(
            text(
                "SELECT coalesce(string_agg(coalesce(response_data::text, ''), ' '), '') "
                "FROM external_data WHERE application_id = :id"
            ),
            {"id": application_id},
        )

    assert pii_row.pan_hash is not None
    assert len(pii_row.pan_hash) == 64
    assert pii_row.has_ciphertext is True
    assert pii_row.has_nonce is True
    assert audit_count >= 5
    assert raw_pan not in audit_text
    assert raw_pan not in external_text
    assert str(payload["user_data"]["monthly_income"]) not in audit_text
    assert str(payload["user_data"]["loan_amount"]) not in audit_text

    metrics = generate_latest().decode("utf-8")
    assert "auditlend_applications_total" in metrics
    assert "auditlend_decision_confidence" in metrics

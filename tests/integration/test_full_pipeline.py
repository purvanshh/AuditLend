import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from models.application import LoanApplication
from services import FailureType, ServiceResult
from tests.conftest import encrypted_application_fields
from worker.tasks import process_application as task_module


class FakeRedis:
    async def aclose(self) -> None:
        return None


def _insert_application(engine, user_data, failure_flags=None) -> str:
    application_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(
            LoanApplication(
                id=application_id,
                idempotency_key=f"pipeline-{application_id}",
                **encrypted_application_fields(user_data),
                failure_flags=failure_flags or {},
                status="PENDING",
            )
        )
        session.commit()
    return str(application_id)


def test_full_worker_pipeline_success(monkeypatch, clean_database, sample_user_data) -> None:
    application_id = _insert_application(clean_database, sample_user_data)

    async def fake_credit_fetch(*args, **kwargs):
        return ServiceResult(success=True, data={"credit_score": 800}, raw_response={"credit_score": 800})

    async def fake_bank_analyze(*args, **kwargs):
        return ServiceResult(success=True, data={"income_stability": 0.9}, raw_response={"income_stability": 0.9})

    async def fake_gst_verify(*args, **kwargs):
        return ServiceResult(success=True, data={"gst_compliant": True}, raw_response={"gst_compliant": True})

    monkeypatch.setattr(task_module.redis_async, "from_url", lambda *args, **kwargs: FakeRedis())
    monkeypatch.setattr(task_module.CreditBureauService, "fetch", fake_credit_fetch)
    monkeypatch.setattr(task_module.BankAnalyzerService, "analyze", fake_bank_analyze)
    monkeypatch.setattr(task_module.GstVerifierService, "verify", fake_gst_verify)

    result = asyncio.run(task_module._process_application(application_id))

    assert result["status"] == "COMPLETED"
    assert result["decision"] == "APPROVE"
    with clean_database.connect() as connection:
        row = connection.execute(
            text("SELECT status, decision, confidence FROM loan_applications WHERE id = :id"),
            {"id": application_id},
        ).one()
        external_count = connection.scalar(text("SELECT count(*) FROM external_data"))
        audit_count = connection.scalar(text("SELECT count(*) FROM audit_logs"))

    assert row.status == "COMPLETED"
    assert row.decision == "APPROVE"
    assert float(row.confidence) == 1.0
    assert external_count == 3
    assert audit_count >= 5


def test_full_worker_pipeline_all_failures_routes_manual_review(monkeypatch, clean_database, sample_user_data) -> None:
    application_id = _insert_application(
        clean_database,
        sample_user_data,
        {
            "credit_bureau": "TIMEOUT",
            "bank_analyzer": "FORMAT_ERROR",
            "gst_verifier": "PAN_MISMATCH",
        },
    )

    async def fake_fetch_external_data(app_id, user_data, failure_flags, redis_client):
        return (
            ServiceResult(
                success=False,
                data={"credit_score": 600},
                failure_type=FailureType.TIMEOUT,
                raw_response={"error": "timeout"},
                fallback_used=True,
            ),
            ServiceResult(
                success=False,
                data=None,
                failure_type=FailureType.FORMAT_ERROR,
                raw_response={"error": "bad format"},
                fallback_used=True,
            ),
            ServiceResult(
                success=False,
                data={"gst_compliant": False},
                failure_type=FailureType.PAN_MISMATCH,
                raw_response={"match": False},
                fallback_used=True,
            ),
        )

    monkeypatch.setattr(task_module.redis_async, "from_url", lambda *args, **kwargs: FakeRedis())
    monkeypatch.setattr(task_module, "_fetch_external_data", fake_fetch_external_data)

    result = asyncio.run(task_module._process_application(application_id))

    assert result["status"] == "MANUAL_REVIEW"
    assert result["decision"] == "NEEDS_REVIEW"
    assert result["confidence"] < 0.6

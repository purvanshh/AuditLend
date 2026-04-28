import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from models.application import LoanApplication
from services import ServiceResult
from worker.tasks import process_application as task_module


class FakeRedis:
    async def aclose(self) -> None:
        return None


def test_worker_redelivery_recovers_processing_application(monkeypatch, clean_database, sample_user_data) -> None:
    application_id = uuid.uuid4()
    with Session(clean_database) as session:
        session.add(
            LoanApplication(
                id=application_id,
                idempotency_key="worker-crash-recovery",
                user_data=sample_user_data,
                failure_flags={},
                status="PROCESSING",
                updated_at=datetime.now(UTC) - timedelta(seconds=600),
            )
        )
        session.commit()

    async def fake_fetch_external_data(app_id, user_data, failure_flags, redis_client):
        return (
            ServiceResult(success=True, data={"credit_score": 800}, raw_response={"credit_score": 800}),
            ServiceResult(success=True, data={"income_stability": 0.9}, raw_response={"income_stability": 0.9}),
            ServiceResult(success=True, data={"gst_compliant": True}, raw_response={"gst_compliant": True}),
        )

    monkeypatch.setattr(task_module.redis_async, "from_url", lambda *args, **kwargs: FakeRedis())
    monkeypatch.setattr(task_module, "_fetch_external_data", fake_fetch_external_data)

    result = asyncio.run(task_module._process_application(str(application_id)))

    assert result["status"] == "COMPLETED"
    with clean_database.connect() as connection:
        status = connection.scalar(
            text("SELECT status FROM loan_applications WHERE id = :id"),
            {"id": str(application_id)},
        )
        audit_steps = connection.execute(
            text("SELECT step FROM audit_logs WHERE application_id = :id ORDER BY id"),
            {"id": str(application_id)},
        ).scalars().all()

    assert status == "COMPLETED"
    assert "PROCESSING_STARTED" in audit_steps
    assert "DECISION_CALCULATION" in audit_steps

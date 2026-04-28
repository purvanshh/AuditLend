import asyncio
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from models.application import LoanApplication
from models.outbox import OutboxMessage
from services import ServiceResult
from tests.conftest import encrypted_application_fields
from worker import outbox_poller
from worker.tasks import process_application as task_module


class FakeRedis:
    async def aclose(self) -> None:
        return None


def test_outbox_delivers_exactly_once(monkeypatch, clean_database) -> None:
    calls: list[tuple[str, list[str], str]] = []
    application_id = str(uuid.uuid4())

    class FakeCelery:
        def send_task(self, task_name, args=None, task_id=None):
            calls.append((task_name, args or [], task_id))

    monkeypatch.setattr("worker.celery_app.celery_app", FakeCelery())

    with Session(clean_database) as session:
        session.add(
            OutboxMessage(
                task_name="worker.tasks.process_application.process_application",
                task_args={"application_id": application_id},
                status="PENDING",
            )
        )
        session.commit()

    assert outbox_poller.poll_outbox_once() == 1
    assert outbox_poller.poll_outbox_once() == 0

    with Session(clean_database) as session:
        message = session.scalars(select(OutboxMessage)).one()

    assert len(calls) == 1
    assert calls[0][1] == [application_id]
    assert message.status == "PROCESSED"
    assert message.processed_at is not None


def test_external_fetches_reused_after_worker_retry(monkeypatch, clean_database, sample_user_data) -> None:
    application_id = uuid.uuid4()
    with Session(clean_database) as session:
        session.add(
            LoanApplication(
                id=application_id,
                idempotency_key=f"external-once-{application_id}",
                **encrypted_application_fields(sample_user_data),
                failure_flags={},
                status="PROCESSING",
            )
        )
        session.commit()

    calls = {"credit": 0, "bank": 0, "gst": 0}

    async def fake_credit_fetch(self, pan, application_id=None, fail_mode=None):
        calls["credit"] += 1
        return ServiceResult(success=True, data={"credit_score": 800}, raw_response={"credit_score": 800})

    async def fake_bank_analyze(self, pan, bank_statement=None, application_id=None, fail_mode=None):
        calls["bank"] += 1
        return ServiceResult(success=True, data={"income_stability": 0.9}, raw_response={"income_stability": 0.9})

    async def fake_gst_verify(self, pan, application_id=None, fail_mode=None):
        calls["gst"] += 1
        return ServiceResult(success=True, data={"gst_compliant": True}, raw_response={"gst_compliant": True})

    monkeypatch.setattr(task_module.CreditBureauService, "fetch", fake_credit_fetch)
    monkeypatch.setattr(task_module.BankAnalyzerService, "analyze", fake_bank_analyze)
    monkeypatch.setattr(task_module.GstVerifierService, "verify", fake_gst_verify)

    asyncio.run(task_module._fetch_external_data(application_id, sample_user_data, {}, FakeRedis()))
    asyncio.run(task_module._fetch_external_data(application_id, sample_user_data, {}, FakeRedis()))

    with clean_database.connect() as connection:
        external_count = connection.scalar(
            text("SELECT count(*) FROM external_data WHERE application_id = :id"),
            {"id": str(application_id)},
        )

    assert calls == {"credit": 1, "bank": 1, "gst": 1}
    assert external_count == 3

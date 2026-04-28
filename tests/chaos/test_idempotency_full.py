from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from models.application import LoanApplication
from tests.conftest import encrypted_application_fields
from worker.tasks import process_application as task_module


def _insert_application(engine, user_data, status="PENDING") -> str:
    application_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(
            LoanApplication(
                id=application_id,
                idempotency_key=f"full-idem-{application_id}",
                **encrypted_application_fields(user_data),
                failure_flags={},
                status=status,
                updated_at=(
                    datetime.now(UTC) - timedelta(seconds=600)
                    if status == "PROCESSING"
                    else None
                ),
            )
        )
        session.commit()
    return str(application_id)


def test_concurrent_requests_create_one_application(api_client, clean_database, sample_apply_payload) -> None:
    def submit() -> dict:
        response = api_client.post("/api/v1/apply-loan", json=sample_apply_payload)
        assert response.status_code in {200, 201}
        return response.json()

    with ThreadPoolExecutor(max_workers=10) as executor:
        responses = list(executor.map(lambda _: submit(), range(10)))

    assert len({response["application_id"] for response in responses}) == 1
    with clean_database.connect() as connection:
        application_count = connection.scalar(text("SELECT count(*) FROM loan_applications"))

    assert application_count == 1


def test_concurrent_worker_claims_allow_only_one_processor(clean_database, sample_user_data) -> None:
    application_id = _insert_application(clean_database, sample_user_data)

    def claim() -> dict:
        return task_module._claim_application(application_id)

    with ThreadPoolExecutor(max_workers=10) as executor:
        claims = list(executor.map(lambda _: claim(), range(10)))

    processing_claims = [claim for claim in claims if claim["terminal_or_locked"] is False]
    locked_claims = [claim for claim in claims if claim["terminal_or_locked"] is True]

    assert len(processing_claims) == 1
    assert len(locked_claims) == 9
    assert all(claim["response"]["status"] == "PROCESSING" for claim in locked_claims)


def test_stale_processing_application_can_be_reclaimed(clean_database, sample_user_data) -> None:
    application_id = _insert_application(clean_database, sample_user_data, status="PROCESSING")

    claim = task_module._claim_application(application_id)

    assert claim["terminal_or_locked"] is False
    assert str(claim["id"]) == application_id

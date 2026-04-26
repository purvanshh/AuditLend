from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text


def test_concurrent_same_idempotency_key_creates_one_application(api_client, clean_database, sample_apply_payload) -> None:
    def submit() -> dict:
        response = api_client.post("/api/v1/apply-loan", json=sample_apply_payload)
        assert response.status_code in {200, 201}
        return response.json()

    with ThreadPoolExecutor(max_workers=10) as executor:
        responses = list(executor.map(lambda _: submit(), range(10)))

    application_ids = {response["application_id"] for response in responses}
    assert len(application_ids) == 1

    with clean_database.connect() as connection:
        application_count = connection.scalar(text("SELECT count(*) FROM loan_applications"))
        idempotency_count = connection.scalar(text("SELECT count(*) FROM idempotency_records"))

    assert application_count == 1
    assert idempotency_count == 1
    assert api_client.enqueued_applications == [next(iter(application_ids))]

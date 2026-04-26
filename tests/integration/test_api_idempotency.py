from sqlalchemy import text


def test_apply_loan_replays_same_idempotency_response(api_client, clean_database, sample_apply_payload) -> None:
    first = api_client.post("/api/v1/apply-loan", json=sample_apply_payload)
    second = api_client.post("/api/v1/apply-loan", json=sample_apply_payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["application_id"] == second.json()["application_id"]
    assert api_client.enqueued_applications == [first.json()["application_id"]]

    with clean_database.connect() as connection:
        application_count = connection.scalar(text("SELECT count(*) FROM loan_applications"))
        idempotency_count = connection.scalar(text("SELECT count(*) FROM idempotency_records"))

    assert application_count == 1
    assert idempotency_count == 1


def test_apply_loan_rejects_same_key_with_different_payload(api_client, sample_apply_payload) -> None:
    first = api_client.post("/api/v1/apply-loan", json=sample_apply_payload)
    changed = {
        **sample_apply_payload,
        "user_data": {
            **sample_apply_payload["user_data"],
            "loan_amount": sample_apply_payload["user_data"]["loan_amount"] + 1,
        },
    }
    second = api_client.post("/api/v1/apply-loan", json=changed)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.headers["content-type"].startswith("application/problem+json")

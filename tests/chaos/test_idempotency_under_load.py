import asyncio

import httpx
import pytest
from sqlalchemy import text

from api.main import app


@pytest.mark.asyncio
async def test_concurrent_same_idempotency_key_creates_one_application(clean_database, sample_apply_payload) -> None:
    async def submit(client: httpx.AsyncClient) -> dict:
        response = await client.post("/api/v1/apply-loan", json=sample_apply_payload)
        assert response.status_code in {200, 201}
        return response.json()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-api-key-for-ci"},
    ) as client:
        responses = await asyncio.gather(*(submit(client) for _ in range(10)))

    application_ids = {response["application_id"] for response in responses}
    assert len(application_ids) == 1

    with clean_database.connect() as connection:
        application_count = connection.scalar(text("SELECT count(*) FROM loan_applications"))
        idempotency_count = connection.scalar(text("SELECT count(*) FROM idempotency_records"))
        outbox_count = connection.scalar(text("SELECT count(*) FROM outbox"))

    assert application_count == 1
    assert idempotency_count == 1
    assert outbox_count == 1

import httpx
import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from api.main import app
from services import FailureType
from services.credit_bureau import CreditBureauService
from services.metrics import task_duration, task_failures


def test_metrics_endpoint_exposes_auditlend_metrics() -> None:
    response = TestClient(app).get("/metrics")

    assert response.status_code == 200
    assert "auditlend_applications_total" in response.text
    assert "auditlend_external_api_requests_total" in response.text


@pytest.mark.asyncio
async def test_external_service_metrics_increment_after_failed_call(monkeypatch) -> None:
    async def no_sleep(delay: float) -> None:
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(408, json={"error": "Request timeout", "request_id": "timeout-1"})

    monkeypatch.setenv("MAX_RETRIES", "0")
    monkeypatch.setattr("services.base.asyncio.sleep", no_sleep)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock") as client:
        service = CreditBureauService(base_url="http://mock", redis_client=None, http_client=client)
        await service.fetch("ABCDE1234F", fail_mode=FailureType.TIMEOUT)

    metrics = generate_latest().decode("utf-8")
    assert 'auditlend_external_api_requests_total{service="credit_bureau",status="TIMEOUT"}' in metrics


def test_task_metrics_are_exported() -> None:
    task_duration.labels(task_name="process_application").observe(0.1)
    task_failures.labels(task_name="process_application", error_type="SYSTEM_ERROR").inc()

    metrics = generate_latest().decode("utf-8")
    assert "auditlend_task_duration_seconds" in metrics
    assert 'auditlend_task_failures_total{error_type="SYSTEM_ERROR",task_name="process_application"}' in metrics

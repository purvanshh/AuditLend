from __future__ import annotations

import time

import httpx
import pytest

import services.base
from services import FailureType
from services.bank_analyzer import BankAnalyzerService
from services.base import CircuitState
from services.credit_bureau import CreditBureauService
from services.gst_verifier import GstVerifierService


PAN = "ABCDE1234F"


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str | int] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value, **kwargs):
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def setex(self, key: str, ttl: int, value):
        self.values[key] = value
        self.expirations[key] = ttl
        return True

    async def incr(self, key: str):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def expire(self, key: str, ttl: int):
        self.expirations[key] = ttl
        return True

    async def delete(self, key: str):
        self.values.pop(key, None)
        self.expirations.pop(key, None)
        return True


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(delay: float) -> None:
        return None

    monkeypatch.setenv("MAX_RETRIES", "3")
    monkeypatch.setenv("RETRY_BACKOFF_BASE_SECONDS", "0")
    monkeypatch.setenv("CIRCUIT_BREAKER_THRESHOLD", "5")
    monkeypatch.setenv("CIRCUIT_BREAKER_TIMEOUT_SECONDS", "120")
    monkeypatch.setattr(services.base.asyncio, "sleep", no_sleep)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock")


@pytest.mark.asyncio
async def test_credit_timeout_retries_then_uses_conservative_fallback() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(408, json={"error": "Request timeout", "request_id": f"req-{attempts}"})

    async with client_for(handler) as client:
        service = CreditBureauService(base_url="http://mock", redis_client=FakeRedis(), http_client=client)
        result = await service.fetch(PAN, fail_mode=FailureType.TIMEOUT)

    assert attempts == 4
    assert result.success is False
    assert result.failure_type == FailureType.TIMEOUT
    assert result.retry_count == 3
    assert result.fallback_used is True
    assert result.data == {"credit_score": 600}


@pytest.mark.asyncio
async def test_circuit_opens_after_service_down_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_RETRIES", "0")
    redis = FakeRedis()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"error": "Service unavailable", "request_id": f"req-{attempts}"})

    async with client_for(handler) as client:
        service = CreditBureauService(base_url="http://mock", redis_client=redis, http_client=client)
        for _ in range(5):
            await service.fetch(PAN, fail_mode=FailureType.SERVICE_DOWN)

        assert await service._circuit_state() == CircuitState.OPEN
        sixth = await service.fetch(PAN, fail_mode=FailureType.SERVICE_DOWN)

    assert attempts == 5
    assert sixth.failure_type == FailureType.SERVICE_DOWN
    assert sixth.fallback_used is True
    assert sixth.data == {"credit_score": 600}


@pytest.mark.asyncio
async def test_circuit_half_open_recovers_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    now = time.monotonic()
    redis.values["circuit:credit_bureau:state"] = CircuitState.OPEN.value
    redis.values["circuit:credit_bureau:last_failure"] = str(now - 121)

    monkeypatch.setenv("CIRCUIT_BREAKER_TIMEOUT_SECONDS", "120")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "pan": PAN,
                "credit_score": 780,
                "last_updated": "2026-04-01T00:00:00Z",
                "request_id": "credit-ok",
            },
        )

    async with client_for(handler) as client:
        service = CreditBureauService(base_url="http://mock", redis_client=redis, http_client=client)
        assert await service._circuit_state() == CircuitState.HALF_OPEN
        result = await service.fetch(PAN)

    assert result.success is True
    assert redis.values["circuit:credit_bureau:state"] == CircuitState.CLOSED.value


@pytest.mark.asyncio
async def test_bank_partial_data_is_non_retryable_and_preserves_available_fields() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={
                "pan": PAN,
                "monthly_inflow": 120000,
                "monthly_outflow": 65000,
                "request_id": "bank-partial",
            },
        )

    async with client_for(handler) as client:
        service = BankAnalyzerService(base_url="http://mock", redis_client=FakeRedis(), http_client=client)
        result = await service.analyze(PAN, fail_mode=FailureType.PARTIAL_DATA)

    assert attempts == 1
    assert result.failure_type == FailureType.PARTIAL_DATA
    assert result.fallback_used is False
    assert result.data["monthly_inflow"] == 120000


@pytest.mark.asyncio
async def test_bank_format_error_does_not_retry() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            400,
            json={"error": "Unable to parse bank statement", "request_id": "bank-bad"},
        )

    async with client_for(handler) as client:
        service = BankAnalyzerService(base_url="http://mock", redis_client=FakeRedis(), http_client=client)
        result = await service.analyze(PAN, fail_mode=FailureType.FORMAT_ERROR)

    assert attempts == 1
    assert result.failure_type == FailureType.FORMAT_ERROR
    assert result.fallback_used is True
    assert result.data is None


@pytest.mark.asyncio
async def test_gst_pan_mismatch_does_not_retry_and_falls_back_to_non_compliant() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={
                "pan": PAN,
                "match": False,
                "error": "PAN does not match GST records",
                "request_id": "gst-mismatch",
            },
        )

    async with client_for(handler) as client:
        service = GstVerifierService(base_url="http://mock", redis_client=FakeRedis(), http_client=client)
        result = await service.verify(PAN, fail_mode=FailureType.PAN_MISMATCH)

    assert attempts == 1
    assert result.failure_type == FailureType.PAN_MISMATCH
    assert result.fallback_used is True
    assert result.data == {"gst_compliant": False}


@pytest.mark.asyncio
async def test_gst_no_record_falls_back_to_non_compliant() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": "No GST record found for this PAN", "request_id": "gst-none"},
        )

    async with client_for(handler) as client:
        service = GstVerifierService(base_url="http://mock", redis_client=FakeRedis(), http_client=client)
        result = await service.verify(PAN, fail_mode=FailureType.NO_RECORD)

    assert result.failure_type == FailureType.NO_RECORD
    assert result.fallback_used is True
    assert result.data == {"gst_compliant": False}

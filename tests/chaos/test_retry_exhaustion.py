import httpx
import pytest

import services.base
from services import FailureType
from services.credit_bureau import CreditBureauService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str | int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value):
        self.values[key] = value

    async def incr(self, key: str):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def expire(self, key: str, ttl: int):
        return None

    async def delete(self, key: str):
        self.values.pop(key, None)


@pytest.mark.asyncio
async def test_retry_exhaustion_uses_credit_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    async def no_sleep(delay: float) -> None:
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(408, json={"error": "Request timeout", "request_id": f"timeout-{attempts}"})

    monkeypatch.setenv("MAX_RETRIES", "3")
    monkeypatch.setenv("RETRY_BACKOFF_BASE_SECONDS", "0")
    monkeypatch.setattr(services.base.asyncio, "sleep", no_sleep)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock") as client:
        service = CreditBureauService(base_url="http://mock", redis_client=FakeRedis(), http_client=client)
        result = await service.fetch("ABCDE1234F", fail_mode=FailureType.TIMEOUT)

    assert attempts == 4
    assert result.failure_type == FailureType.TIMEOUT
    assert result.retry_count == 3
    assert result.fallback_used is True
    assert result.data == {"credit_score": 600}

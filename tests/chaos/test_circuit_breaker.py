import httpx
import pytest

from services import FailureType
from services.base import CircuitState
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
async def test_circuit_opens_and_short_circuits_after_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    redis = FakeRedis()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"error": "Service unavailable", "request_id": f"down-{attempts}"})

    monkeypatch.setenv("MAX_RETRIES", "0")
    monkeypatch.setenv("CIRCUIT_BREAKER_THRESHOLD", "5")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock") as client:
        service = CreditBureauService(base_url="http://mock", redis_client=redis, http_client=client)
        for _ in range(5):
            await service.fetch("ABCDE1234F", fail_mode=FailureType.SERVICE_DOWN)
        sixth = await service.fetch("ABCDE1234F", fail_mode=FailureType.SERVICE_DOWN)

    assert await service._circuit_state() == CircuitState.OPEN
    assert attempts == 5
    assert sixth.fallback_used is True
    assert sixth.data == {"credit_score": 600}

import asyncio

import httpx
import pytest

from services import FailureType
from services.credit_bureau import CreditBureauService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str | int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value, **kwargs):
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def incr(self, key: str):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def expire(self, key: str, ttl: int):
        return None

    async def delete(self, key: str):
        self.values.pop(key, None)


@pytest.mark.asyncio
async def test_half_open_allows_only_one_probe() -> None:
    attempts = 0
    redis = FakeRedis()
    redis.values["circuit:credit_bureau:state"] = "HALF_OPEN"

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"credit_score": 800, "request_id": "probe-ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock") as client:
        service = CreditBureauService(base_url="http://mock", redis_client=redis, http_client=client)
        results = await asyncio.gather(
            *[
                service.fetch("ABCDE1234F", fail_mode=FailureType.SERVICE_DOWN)
                for _ in range(5)
            ]
        )

    assert attempts == 1
    assert sum(result.success for result in results) == 1
    assert sum(result.failure_type == FailureType.SERVICE_DOWN for result in results) == 4


@pytest.mark.asyncio
async def test_half_open_probe_success_closes_circuit() -> None:
    redis = FakeRedis()
    redis.values["circuit:credit_bureau:state"] = "HALF_OPEN"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"credit_score": 800, "request_id": "probe-ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock") as client:
        service = CreditBureauService(base_url="http://mock", redis_client=redis, http_client=client)
        result = await service.fetch("ABCDE1234F")

    assert result.success is True
    assert redis.values["circuit:credit_bureau:state"] == "CLOSED"
    assert "circuit:credit_bureau:probe_lock" not in redis.values


@pytest.mark.asyncio
async def test_half_open_probe_failure_reopens_circuit() -> None:
    redis = FakeRedis()
    redis.values["circuit:credit_bureau:state"] = "HALF_OPEN"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down", "request_id": "probe-failed"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock") as client:
        service = CreditBureauService(base_url="http://mock", redis_client=redis, http_client=client)
        result = await service.fetch("ABCDE1234F")

    assert result.failure_type == FailureType.SERVICE_DOWN
    assert redis.values["circuit:credit_bureau:state"] == "OPEN"
    assert "circuit:credit_bureau:probe_lock" not in redis.values

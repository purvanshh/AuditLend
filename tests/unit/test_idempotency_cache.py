import pytest

from api.routes import applications


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        self.values[key] = value
        self.ttls[key] = ttl

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_redis_idempotency_cache_roundtrip(monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(applications.redis_async, "from_url", lambda *args, **kwargs: fake)
    monkeypatch.setenv("IDEMPOTENCY_CACHE_TTL_SECONDS", "123")

    payload = {
        "public": {"application_id": "app-1", "status": "PENDING"},
        "_request_hash": "hash-1",
    }

    await applications._redis_idempotency_set("idem-1", payload)
    cached = await applications._redis_idempotency_get("idem-1")

    assert cached == payload
    assert fake.ttls["idempotent:idem-1"] == 123


@pytest.mark.asyncio
async def test_redis_idempotency_cache_failure_falls_back(monkeypatch) -> None:
    class BrokenRedis:
        async def get(self, key: str):
            raise ConnectionError("down")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(applications.redis_async, "from_url", lambda *args, **kwargs: BrokenRedis())

    assert await applications._redis_idempotency_get("idem-1") is None

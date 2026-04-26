import asyncio
import inspect
import os
from enum import StrEnum
from time import monotonic
from typing import Any

import httpx
import structlog

from services import FailureType, ServiceResult


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class BaseExternalService:
    def __init__(
        self,
        base_url: str,
        service_name: str,
        redis_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.redis = redis_client
        self.http_client = http_client
        self.logger = structlog.get_logger().bind(service=service_name)

    async def call(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        fail_mode: FailureType | None = None,
        application_id: str | None = None,
    ) -> ServiceResult:
        if await self._circuit_state() == CircuitState.OPEN:
            self.logger.warning(
                "circuit_open_short_circuit",
                application_id=application_id,
                step="EXTERNAL_SERVICE_CALL",
            )
            return ServiceResult(
                success=False,
                failure_type=FailureType.SERVICE_DOWN,
                fallback_used=True,
            )

        retry_count = 0
        last_result: ServiceResult | None = None
        max_retries = self._env_int("MAX_RETRIES", 3)

        for attempt in range(max_retries + 1):
            result = await self._attempt_call(method, path, params, body, fail_mode)
            result.retry_count = retry_count
            last_result = result

            if result.success:
                await self._record_success()
                self.logger.info(
                    "external_service_success",
                    application_id=application_id,
                    step="EXTERNAL_SERVICE_CALL",
                    failure_type=None,
                    retry_count=retry_count,
                    latency_ms=result.latency_ms,
                )
                return result

            if result.failure_type == FailureType.SERVICE_DOWN:
                await self._record_service_down()

            if result.failure_type not in self.retryable_failures() or attempt == max_retries:
                result.fallback_used = result.failure_type in self.retryable_failures()
                self.logger.warning(
                    "external_service_failed",
                    application_id=application_id,
                    step="EXTERNAL_SERVICE_CALL",
                    failure_type=result.failure_type.value if result.failure_type else None,
                    retry_count=retry_count,
                    fallback_used=result.fallback_used,
                    latency_ms=result.latency_ms,
                )
                return result

            retry_count += 1
            delay = self._retry_delay(attempt)
            self.logger.warning(
                "external_service_retry",
                application_id=application_id,
                step="EXTERNAL_SERVICE_CALL",
                failure_type=result.failure_type.value if result.failure_type else None,
                attempt=attempt + 1,
                retry_count=retry_count,
                retry_delay_seconds=delay,
            )
            await asyncio.sleep(delay)

        return last_result or ServiceResult(success=False, failure_type=FailureType.SERVICE_DOWN, fallback_used=True)

    def retryable_failures(self) -> set[FailureType]:
        return {FailureType.TIMEOUT, FailureType.SERVICE_DOWN}

    async def _attempt_call(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        body: dict[str, Any] | None,
        fail_mode: FailureType | None,
    ) -> ServiceResult:
        query = dict(params or {})
        if fail_mode is not None:
            query["fail_mode"] = fail_mode.value

        started_at = monotonic()
        try:
            client = self.http_client or httpx.AsyncClient(timeout=10.0)
            close_client = self.http_client is None
            try:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=query,
                    json=body,
                )
            finally:
                if close_client:
                    await client.aclose()
        except httpx.TimeoutException:
            return ServiceResult(
                success=False,
                failure_type=FailureType.TIMEOUT,
                latency_ms=self._latency_ms(started_at),
            )
        except httpx.HTTPError as exc:
            self.logger.warning("external_service_http_error", error=str(exc))
            return ServiceResult(
                success=False,
                failure_type=FailureType.SERVICE_DOWN,
                latency_ms=self._latency_ms(started_at),
            )

        raw_response = self._json_response(response)
        failure_type = self.classify_response(response, raw_response)
        request_id = self._request_id(raw_response)

        return ServiceResult(
            success=failure_type in {None, FailureType.SUCCESS},
            data=raw_response if failure_type in {None, FailureType.SUCCESS} else None,
            failure_type=None if failure_type in {None, FailureType.SUCCESS} else failure_type,
            raw_response=raw_response,
            latency_ms=self._latency_ms(started_at),
            request_id=request_id,
        )

    def classify_response(self, response: httpx.Response, raw_response: dict[str, Any] | None) -> FailureType | None:
        if response.status_code == 408:
            return FailureType.TIMEOUT
        if response.status_code >= 500:
            return FailureType.SERVICE_DOWN
        if response.status_code == 404:
            return FailureType.NO_RECORD
        if response.status_code == 400:
            return FailureType.FORMAT_ERROR
        if response.status_code >= 400:
            return FailureType.SERVICE_DOWN
        return None

    async def _circuit_state(self) -> CircuitState:
        if self.redis is None:
            return CircuitState.CLOSED

        state_key = self._circuit_key("state")
        state = await self._redis_get(state_key)
        if state is None:
            return CircuitState.CLOSED
        if isinstance(state, bytes):
            state = state.decode("utf-8")
        if state == CircuitState.OPEN.value:
            last_failure = await self._redis_get(self._circuit_key("last_failure"))
            if isinstance(last_failure, bytes):
                last_failure = last_failure.decode("utf-8")
            if last_failure is not None:
                elapsed = monotonic() - float(last_failure)
                if elapsed >= self._env_int("CIRCUIT_BREAKER_TIMEOUT_SECONDS", 120):
                    await self._redis_set(state_key, CircuitState.HALF_OPEN.value)
                    self.logger.info("circuit_half_open", step="CIRCUIT_BREAKER")
                    return CircuitState.HALF_OPEN
        return CircuitState(state)

    async def _record_success(self) -> None:
        if self.redis is None:
            return
        await self._redis_set(self._circuit_key("state"), CircuitState.CLOSED.value)
        await self._redis_delete(self._circuit_key("failure_count"))
        await self._redis_delete(self._circuit_key("last_failure"))

    async def _record_service_down(self) -> None:
        if self.redis is None:
            return

        count = await self._redis_incr(self._circuit_key("failure_count"))
        await self._redis_expire(self._circuit_key("failure_count"), self._env_int("CIRCUIT_BREAKER_WINDOW_SECONDS", 60))
        await self._redis_set(self._circuit_key("last_failure"), str(monotonic()))
        threshold = self._env_int("CIRCUIT_BREAKER_THRESHOLD", 5)
        if count >= threshold:
            await self._redis_set(self._circuit_key("state"), CircuitState.OPEN.value)
            self.logger.warning("circuit_opened", step="CIRCUIT_BREAKER", failure_count=count)

    def _circuit_key(self, suffix: str) -> str:
        return f"circuit:{self.service_name}:{suffix}"

    def _retry_delay(self, attempt: int) -> float:
        base = self._env_float("RETRY_BACKOFF_BASE_SECONDS", 2.0)
        deterministic_jitter = ((attempt + 1) * 137 % 500) / 1000
        return base * (2**attempt) + deterministic_jitter

    def _json_response(self, response: httpx.Response) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if isinstance(payload, dict) and isinstance(payload.get("detail"), dict):
            return payload["detail"]
        return payload if isinstance(payload, dict) else None

    def _request_id(self, raw_response: dict[str, Any] | None) -> str | None:
        return raw_response.get("request_id") if raw_response else None

    def _latency_ms(self, started_at: float) -> float:
        return round((monotonic() - started_at) * 1000, 2)

    def _env_int(self, name: str, default: int) -> int:
        return int(os.getenv(name, str(default)))

    def _env_float(self, name: str, default: float) -> float:
        return float(os.getenv(name, str(default)))

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _redis_get(self, key: str) -> Any:
        return await self._maybe_await(self.redis.get(key))

    async def _redis_set(self, key: str, value: Any) -> None:
        await self._maybe_await(self.redis.set(key, value))

    async def _redis_setex(self, key: str, ttl: int, value: Any) -> None:
        await self._maybe_await(self.redis.setex(key, ttl, value))

    async def _redis_incr(self, key: str) -> int:
        return int(await self._maybe_await(self.redis.incr(key)))

    async def _redis_expire(self, key: str, ttl: int) -> None:
        await self._maybe_await(self.redis.expire(key, ttl))

    async def _redis_delete(self, key: str) -> None:
        await self._maybe_await(self.redis.delete(key))

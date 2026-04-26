import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from services import FailureType, ServiceResult
from services.base import BaseExternalService


class CreditBureauService(BaseExternalService):
    def __init__(
        self,
        base_url: str | None = None,
        redis_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            base_url or os.getenv("CREDIT_BUREAU_URL", "http://credit-bureau:8001"),
            "credit_bureau",
            redis_client,
            http_client,
        )

    async def fetch(
        self,
        pan: str,
        application_id: str | None = None,
        fail_mode: FailureType | None = None,
    ) -> ServiceResult:
        result = await self.call(
            "GET",
            "/credit-score",
            params={"pan": pan},
            fail_mode=fail_mode,
            application_id=application_id,
        )

        if result.success and result.data and self._is_stale(result.data):
            result.success = False
            result.failure_type = FailureType.STALE_DATA
            result.data = result.raw_response
            return result

        if result.success:
            return result

        if result.failure_type in {FailureType.TIMEOUT, FailureType.SERVICE_DOWN}:
            result.data = {"credit_score": 600}
            result.fallback_used = True
        return result

    def _is_stale(self, data: dict[str, Any]) -> bool:
        last_updated = data.get("last_updated")
        if not isinstance(last_updated, str):
            return False
        parsed = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
        return parsed < datetime.now(UTC) - timedelta(days=60)

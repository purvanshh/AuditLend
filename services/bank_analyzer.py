import os
from typing import Any

import httpx

from services import FailureType, ServiceResult
from services.base import BaseExternalService


class BankAnalyzerService(BaseExternalService):
    def __init__(
        self,
        base_url: str | None = None,
        redis_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            base_url or os.getenv("BANK_ANALYZER_URL", "http://bank-analyzer:8002"),
            "bank_analyzer",
            redis_client,
            http_client,
        )

    async def analyze(
        self,
        pan: str,
        bank_statement: list[dict] | None = None,
        application_id: str | None = None,
        fail_mode: FailureType | None = None,
    ) -> ServiceResult:
        result = await self.call(
            "POST",
            "/analyze",
            body={"pan": pan, "bank_statement": bank_statement or []},
            fail_mode=fail_mode,
            application_id=application_id,
        )

        if result.success and result.data and "income_stability" not in result.data:
            result.success = False
            result.failure_type = FailureType.PARTIAL_DATA
            result.data = result.raw_response
            result.fallback_used = False
            return result

        if result.failure_type == FailureType.FORMAT_ERROR:
            result.data = None
            result.fallback_used = True

        return result

import os
from typing import Any

import httpx

from services import FailureType, ServiceResult
from services.base import BaseExternalService


class GstVerifierService(BaseExternalService):
    def __init__(
        self,
        base_url: str | None = None,
        redis_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            base_url or os.getenv("GST_VERIFIER_URL", "http://gst-verifier:8003"),
            "gst_verifier",
            redis_client,
            http_client,
        )

    async def verify(
        self,
        pan: str,
        application_id: str | None = None,
        fail_mode: FailureType | None = None,
    ) -> ServiceResult:
        result = await self.call(
            "GET",
            "/verify-gst",
            params={"pan": pan},
            fail_mode=fail_mode,
            application_id=application_id,
        )

        if result.success and result.data and result.data.get("match") is False:
            result.success = False
            result.failure_type = FailureType.PAN_MISMATCH
            result.data = {"gst_compliant": False}
            result.fallback_used = True
            return result

        if result.failure_type in {FailureType.PAN_MISMATCH, FailureType.NO_RECORD}:
            result.data = {"gst_compliant": False}
            result.fallback_used = True

        return result

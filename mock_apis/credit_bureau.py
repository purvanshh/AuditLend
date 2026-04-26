import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from time import perf_counter

import structlog
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse


app = FastAPI(title="AuditLend Credit Bureau Mock")
logger = structlog.get_logger()


class CreditFailMode(StrEnum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    STALE_DATA = "STALE_DATA"
    SERVICE_DOWN = "SERVICE_DOWN"


def _pan_hash(pan: str) -> str:
    return hashlib.sha256(pan.encode("utf-8")).hexdigest()


def _request_id(pan: str) -> str:
    return f"credit_{uuid.uuid4().hex}"


def _credit_score(pan: str) -> int:
    seed = int(_pan_hash(pan)[:8], 16)
    return 300 + (seed % 601)


def _success_payload(pan: str, last_updated: datetime) -> dict[str, str | int]:
    return {
        "pan": pan,
        "credit_score": _credit_score(pan),
        "last_updated": last_updated.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "bureau": "AuditLendMock",
        "request_id": _request_id(pan),
    }


def _log_request(pan: str, fail_mode: CreditFailMode, status_code: int, started_at: float) -> None:
    logger.info(
        "mock_request",
        service="credit-bureau",
        pan_hash=_pan_hash(pan),
        fail_mode=fail_mode.value,
        status_code=status_code,
        latency_ms=round((perf_counter() - started_at) * 1000, 2),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "credit-bureau-mock"}


@app.get("/credit-score")
def credit_score(
    pan: str = Query(..., pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$"),
    fail_mode: CreditFailMode = CreditFailMode.SUCCESS,
) -> dict[str, str | int]:
    started_at = perf_counter()

    if fail_mode == CreditFailMode.TIMEOUT:
        time.sleep(35)
        _log_request(pan, fail_mode, 408, started_at)
        return JSONResponse(
            status_code=408,
            content={"error": "Request timeout", "request_id": _request_id(pan)},
        )

    if fail_mode == CreditFailMode.SERVICE_DOWN:
        _log_request(pan, fail_mode, 503, started_at)
        return JSONResponse(
            status_code=503,
            content={"error": "Service unavailable", "request_id": _request_id(pan)},
        )

    now = datetime.now(UTC)
    last_updated = now - timedelta(days=90) if fail_mode == CreditFailMode.STALE_DATA else datetime(2026, 4, 1, tzinfo=UTC)
    payload = _success_payload(pan, last_updated)
    _log_request(pan, fail_mode, 200, started_at)
    return payload

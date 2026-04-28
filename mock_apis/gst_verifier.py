import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from time import perf_counter

import structlog
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse


app = FastAPI(title="AuditLend GST Verifier Mock")
logger = structlog.get_logger()


class GstFailMode(StrEnum):
    SUCCESS = "SUCCESS"
    PAN_MISMATCH = "PAN_MISMATCH"
    NO_RECORD = "NO_RECORD"


def _pan_hash(pan: str) -> str:
    return hashlib.sha256(pan.encode("utf-8")).hexdigest()


def _seed(pan: str) -> int:
    return int(_pan_hash(pan)[:8], 16)


def _request_id(pan: str, fail_mode: GstFailMode) -> str:
    hour_bucket = datetime.now(UTC).strftime("%Y%m%d%H")
    return hashlib.sha256(f"{pan}:{fail_mode.value}:{hour_bucket}".encode("utf-8")).hexdigest()[:12]


def _log_request(pan: str, fail_mode: GstFailMode, status_code: int, started_at: float) -> None:
    logger.info(
        "mock_request",
        service="gst-verifier",
        pan_hash=_pan_hash(pan),
        fail_mode=fail_mode.value,
        status_code=status_code,
        latency_ms=round((perf_counter() - started_at) * 1000, 2),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "gst-verifier-mock"}


@app.get("/verify-gst")
def verify_gst(
    pan: str = Query(..., pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$"),
    fail_mode: GstFailMode = GstFailMode.SUCCESS,
) -> dict[str, str | bool | int]:
    started_at = perf_counter()

    if fail_mode == GstFailMode.PAN_MISMATCH:
        _log_request(pan, fail_mode, 200, started_at)
        return {
            "pan": pan,
            "match": False,
            "error": "PAN does not match GST records",
            "request_id": _request_id(pan, fail_mode),
        }

    if fail_mode == GstFailMode.NO_RECORD:
        _log_request(pan, fail_mode, 404, started_at)
        return JSONResponse(
            status_code=404,
            content={"error": "No GST record found for this PAN", "request_id": _request_id(pan, fail_mode)},
        )

    payload = {
        "pan": pan,
        "gst_compliant": True,
        "annual_turnover": 1_000_000 + (_seed(pan) % 4_000_001),
        "filing_status": "REGULAR",
        "request_id": _request_id(pan, fail_mode),
    }
    _log_request(pan, fail_mode, 200, started_at)
    return payload

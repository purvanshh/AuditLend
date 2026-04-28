import hashlib
import json
from enum import StrEnum
from time import perf_counter

import structlog
from fastapi import FastAPI, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from services.logging import setup_logging

setup_logging()
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
    payload = json.dumps({"pan": pan, "fail_mode": fail_mode.value}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "Validation error", "details": jsonable_encoder(exc.errors())})


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

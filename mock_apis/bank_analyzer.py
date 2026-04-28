import hashlib
import json
from enum import StrEnum
from time import perf_counter

import structlog
from fastapi import FastAPI, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.logging import setup_logging

setup_logging()
app = FastAPI(title="AuditLend Bank Analyzer Mock")
logger = structlog.get_logger()


class BankFailMode(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_DATA = "PARTIAL_DATA"
    FORMAT_ERROR = "FORMAT_ERROR"


class AnalyzeRequest(BaseModel):
    pan: str = Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
    bank_statement: list[dict] = []


def _pan_hash(pan: str) -> str:
    return hashlib.sha256(pan.encode("utf-8")).hexdigest()


def _seed(pan: str) -> int:
    return int(_pan_hash(pan)[:8], 16)


def _request_id(pan: str, fail_mode: BankFailMode) -> str:
    payload = json.dumps({"pan": pan, "fail_mode": fail_mode.value}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _analysis(pan: str, fail_mode: BankFailMode) -> dict[str, str | int | float]:
    seed = _seed(pan)
    monthly_inflow = 80_000 + (seed % 90_001)
    monthly_outflow = int(monthly_inflow * (0.35 + ((seed >> 4) % 30) / 100))
    average_balance = int(monthly_inflow * (0.25 + ((seed >> 8) % 50) / 100))
    income_stability = round(0.5 + ((seed >> 12) % 46) / 100, 2)
    return {
        "pan": pan,
        "average_balance": average_balance,
        "income_stability": income_stability,
        "monthly_inflow": monthly_inflow,
        "monthly_outflow": monthly_outflow,
        "irregular_transactions": seed % 6,
        "request_id": _request_id(pan, fail_mode),
    }


def _log_request(pan: str, fail_mode: BankFailMode, status_code: int, started_at: float) -> None:
    logger.info(
        "mock_request",
        service="bank-analyzer",
        pan_hash=_pan_hash(pan),
        fail_mode=fail_mode.value,
        status_code=status_code,
        latency_ms=round((perf_counter() - started_at) * 1000, 2),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "bank-analyzer-mock"}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "Validation error", "details": jsonable_encoder(exc.errors())})


@app.post("/analyze")
def analyze(
    request: AnalyzeRequest,
    fail_mode: BankFailMode = Query(BankFailMode.SUCCESS),
) -> dict[str, str | int | float]:
    started_at = perf_counter()

    if fail_mode == BankFailMode.FORMAT_ERROR:
        _log_request(request.pan, fail_mode, 400, started_at)
        return JSONResponse(
            status_code=400,
            content={
                "error": "Unable to parse bank statement",
                "details": "Unexpected format at line 42",
                "request_id": _request_id(request.pan, fail_mode),
            },
        )

    payload = _analysis(request.pan, fail_mode)
    if fail_mode == BankFailMode.PARTIAL_DATA:
        _log_request(request.pan, fail_mode, 200, started_at)
        return {
            "pan": request.pan,
            "monthly_inflow": payload["monthly_inflow"],
            "monthly_outflow": payload["monthly_outflow"],
            "request_id": payload["request_id"],
        }

    _log_request(request.pan, fail_mode, 200, started_at)
    return payload

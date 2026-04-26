from dataclasses import dataclass
from enum import StrEnum


class FailureType(StrEnum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    STALE_DATA = "STALE_DATA"
    SERVICE_DOWN = "SERVICE_DOWN"
    PARTIAL_DATA = "PARTIAL_DATA"
    FORMAT_ERROR = "FORMAT_ERROR"
    PAN_MISMATCH = "PAN_MISMATCH"
    NO_RECORD = "NO_RECORD"


@dataclass
class ServiceResult:
    success: bool
    data: dict | None = None
    failure_type: FailureType | None = None
    raw_response: dict | None = None
    latency_ms: float = 0.0
    fallback_used: bool = False
    retry_count: int = 0
    request_id: str | None = None

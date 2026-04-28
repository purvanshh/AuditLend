from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CreditBureauFailureMode(StrEnum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    STALE_DATA = "STALE_DATA"
    SERVICE_DOWN = "SERVICE_DOWN"


class BankAnalyzerFailureMode(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_DATA = "PARTIAL_DATA"
    FORMAT_ERROR = "FORMAT_ERROR"


class GSTVerifierFailureMode(StrEnum):
    SUCCESS = "SUCCESS"
    PAN_MISMATCH = "PAN_MISMATCH"
    NO_RECORD = "NO_RECORD"


class FailureFlags(BaseModel):
    credit_bureau: CreditBureauFailureMode | None = None
    bank_analyzer: BankAnalyzerFailureMode | None = None
    gst_verifier: GSTVerifierFailureMode | None = None


class UserData(BaseModel):
    name: str
    pan: str = Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
    monthly_income: float = Field(gt=0)
    existing_emis: float = Field(ge=0)
    loan_amount: float = Field(gt=0)
    tenure_months: int = Field(gt=0)
    bank_statement: list[dict] = Field(default_factory=list)


class ApplyLoanRequest(BaseModel):
    idempotency_key: str = Field(max_length=255)
    user_data: UserData
    failure_flags: FailureFlags | None = None


class ApplyLoanResponse(BaseModel):
    application_id: str
    status: str
    message: str = "Application received and queued for processing"


class StatusResponse(BaseModel):
    application_id: str
    status: str
    updated_at: datetime | None = None

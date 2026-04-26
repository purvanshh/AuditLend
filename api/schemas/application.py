from datetime import datetime

from pydantic import BaseModel, Field

from services import FailureType


class FailureFlags(BaseModel):
    credit_bureau: FailureType | None = None
    bank_analyzer: FailureType | None = None
    gst_verifier: FailureType | None = None


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

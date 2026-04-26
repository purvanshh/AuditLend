from pydantic import BaseModel, Field


class UserData(BaseModel):
    name: str
    pan: str = Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
    monthly_income: float = Field(gt=0)
    existing_emis: float = Field(ge=0)
    loan_amount: float = Field(gt=0)
    tenure_months: int = Field(gt=0)


class ApplyLoanResponse(BaseModel):
    application_id: str
    status: str

from pydantic import BaseModel, Field


class DecisionResponse(BaseModel):
    application_id: str
    decision: str | None = None
    confidence: float | None = None
    factors: list[str] = Field(default_factory=list)
    rule_version: str | None = None


class DecisionPendingResponse(BaseModel):
    status: str
    message: str = "Decision not yet available"

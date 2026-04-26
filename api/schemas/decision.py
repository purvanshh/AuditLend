from pydantic import BaseModel


class DecisionResponse(BaseModel):
    application_id: str
    decision: str | None = None
    confidence: float | None = None
    factors: list[str] = []
    rule_set_version: str | None = None

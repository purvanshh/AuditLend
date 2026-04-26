from pydantic import BaseModel


class ExplanationResponse(BaseModel):
    application_id: str
    decision: str | None = None
    summary: str
    factors: list[dict[str, str]] = []
    rule_version: str | None = None

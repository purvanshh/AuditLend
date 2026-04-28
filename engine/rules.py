from enum import StrEnum
from typing import Any

from services import FailureType


class Decision(StrEnum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


def evaluate(
    risk_score: float,
    credit_score: int | None,
    dti: float,
    failure_types: list[FailureType],
    gst_compliant: bool | None,
) -> tuple[Decision, list[str]]:
    """
    Pure function. Evaluates score-based rules in priority order.
    First matching rule wins.
    Returns (decision, list of factor strings for audit/explanation).
    """
    effective_risk_score = min(risk_score, 54.0) if gst_compliant is False else risk_score

    factors = [
        f"risk_score (raw) = {risk_score:.2f}",
        f"credit_score (decision_input) = {_display_value(credit_score)}",
        f"dti (computed) = {dti:.2f}",
        f"gst_compliant (decision_input) = {_display_value(gst_compliant)}",
    ]
    if effective_risk_score != risk_score:
        factors.append(f"gst_gate (applied) = risk_score capped at {effective_risk_score:.2f}")
    factors.append(f"risk_score (effective) = {effective_risk_score:.2f}")

    if failure_types:
        failures = ", ".join(failure.value for failure in failure_types)
        factors.append(f"data_reliability_flags = {failures}")
    else:
        factors.append("data_reliability_flags = none")

    if effective_risk_score >= 70 and len(failure_types) == 0:
        factors.append("rule = Strong risk score with all data sources verified")
        return Decision.APPROVE, factors

    if effective_risk_score >= 55 and dti < 0.5:
        factors.append("rule = Moderate risk score within acceptable DTI")
        return Decision.APPROVE, factors

    if effective_risk_score < 35 or dti > 0.6:
        factors.append("rule = Risk score or DTI exceeds decline threshold")
        return Decision.DECLINE, factors

    factors.append("rule = Risk profile requires manual assessment")
    return Decision.NEEDS_REVIEW, factors


def _display_value(value: object | None) -> str:
    return "unknown" if value is None else str(value)


RULES: list[dict[str, Any]] = [
    {
        "decision": Decision.APPROVE,
        "description": "Strong risk score with all data sources verified",
    },
    {
        "decision": Decision.APPROVE,
        "description": "Moderate risk score within acceptable DTI",
    },
    {
        "decision": Decision.DECLINE,
        "description": "Risk score or DTI exceeds decline threshold",
    },
    {
        "decision": Decision.NEEDS_REVIEW,
        "description": "Risk profile requires manual assessment",
    },
]

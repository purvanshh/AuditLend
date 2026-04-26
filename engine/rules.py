from enum import StrEnum
from typing import Any

from services import FailureType


class Decision(StrEnum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


def _coerce_credit_score(credit_score: int | None) -> tuple[int, str]:
    if credit_score is None:
        return 600, "default"
    return credit_score, "live"


def _coerce_income_stability(income_stability: float | None) -> tuple[float, str]:
    if income_stability is None:
        return 0.5, "default"
    return income_stability, "live"


def _coerce_gst_compliance(gst_compliant: bool | None) -> tuple[bool, str]:
    if gst_compliant is None:
        return False, "default"
    return gst_compliant, "live"


def evaluate(
    credit_score: int | None,
    income_stability: float | None,
    dti: float,
    gst_compliant: bool | None,
    failure_types: list[FailureType],
    source_overrides: dict[str, str] | None = None,
) -> tuple[Decision, list[str]]:
    """
    Pure function. Evaluates rules in priority order.
    First matching rule wins.
    Returns (decision, list of factor strings for audit/explanation).
    """
    score, score_source = _coerce_credit_score(credit_score)
    stability, stability_source = _coerce_income_stability(income_stability)
    gst, gst_source = _coerce_gst_compliance(gst_compliant)
    sources = source_overrides or {}

    score_source = sources.get("credit_score", score_source)
    stability_source = sources.get("income_stability", stability_source)
    gst_source = sources.get("gst_compliant", gst_source)

    factors = [
        f"credit_score ({score_source}) = {score}",
        f"income_stability ({stability_source}) = {stability}",
        f"dti (computed) = {dti:.2f}",
        f"gst_compliant ({gst_source}) = {gst}",
    ]

    if failure_types:
        failures = ", ".join(failure.value for failure in failure_types)
        factors.append(f"data_reliability_flags = {failures}")
    else:
        factors.append("data_reliability_flags = none")

    if score >= 750 and stability >= 0.7 and dti < 0.4 and len(failure_types) == 0:
        factors.append("rule = Strong profile with all data sources verified")
        return Decision.APPROVE, factors

    if score >= 650 and stability >= 0.5 and dti < 0.5:
        factors.append("rule = Moderate profile within acceptable risk thresholds")
        return Decision.APPROVE, factors

    if score < 600 or dti >= 0.6:
        factors.append("rule = Risk factors exceed thresholds")
        return Decision.DECLINE, factors

    factors.append("rule = Application requires manual assessment")
    return Decision.NEEDS_REVIEW, factors


RULES: list[dict[str, Any]] = [
    {
        "decision": Decision.APPROVE,
        "description": "Strong profile with all data sources verified",
    },
    {
        "decision": Decision.APPROVE,
        "description": "Moderate profile within acceptable risk thresholds",
    },
    {
        "decision": Decision.DECLINE,
        "description": "Risk factors exceed thresholds",
    },
    {
        "decision": Decision.NEEDS_REVIEW,
        "description": "Application requires manual assessment",
    },
]

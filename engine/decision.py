import os
from dataclasses import asdict, dataclass
from typing import Any

from engine.confidence import compute_data_reliability, compute_decision_confidence
from engine.rules import Decision, evaluate
from engine.scoring import compute_risk_score
from services import FailureType, ServiceResult


@dataclass(frozen=True)
class DecisionOutput:
    decision: Decision
    confidence: float
    data_reliability: float
    risk_score: float
    factors: list[str]
    penalty_reasons: list[str]
    rule_version: str
    requires_manual_review: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decision"] = self.decision.value
        return payload


def compute_decision(
    credit_result: ServiceResult,
    bank_result: ServiceResult,
    gst_result: ServiceResult,
    user_data: dict[str, Any],
    confidence_threshold: float = 0.6,
    rule_version: str = "RULE_SET_V1",
) -> DecisionOutput:
    """
    Orchestrates extraction, risk scoring, calibrated confidence, and manual review override.
    This function is deterministic and side-effect free.
    """
    monthly_income = float(user_data["monthly_income"])
    existing_emis = float(user_data.get("existing_emis", 0))
    dti = existing_emis / monthly_income

    credit_score = _extract_credit_score(credit_result)
    income_stability = _extract_income_stability(bank_result)
    gst_compliant = _extract_gst_compliance(gst_result)

    failure_types = _collect_failure_types(credit_result, bank_result, gst_result)
    used_fallback_credit = (
        credit_result.fallback_used
        and credit_result.failure_type in {FailureType.TIMEOUT, FailureType.SERVICE_DOWN}
    )

    risk_score, score_breakdown = compute_risk_score(
        credit_score,
        income_stability,
        dti,
        gst_compliant,
        failure_types,
    )

    decision, factors = evaluate(
        risk_score,
        credit_score,
        dti,
        failure_types,
        gst_compliant,
    )
    factors = score_breakdown + factors

    data_reliability, penalty_reasons = compute_data_reliability(failure_types, used_fallback_credit)
    confidence, confidence_reasons = compute_decision_confidence(
        risk_score,
        decision,
        data_reliability,
        failure_types,
    )
    penalty_reasons.extend(confidence_reasons)

    requires_manual_review = confidence < confidence_threshold
    if requires_manual_review:
        decision = Decision.NEEDS_REVIEW
        factors.append("Confidence below threshold - routed to manual review")

    return DecisionOutput(
        decision=decision,
        confidence=confidence,
        data_reliability=data_reliability,
        risk_score=risk_score,
        factors=factors,
        penalty_reasons=penalty_reasons,
        rule_version=rule_version,
        requires_manual_review=requires_manual_review,
    )


def compute_decision_from_env(
    credit_result: ServiceResult,
    bank_result: ServiceResult,
    gst_result: ServiceResult,
    user_data: dict[str, Any],
) -> DecisionOutput:
    return compute_decision(
        credit_result,
        bank_result,
        gst_result,
        user_data,
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.6")),
        rule_version=os.getenv("RULE_SET_VERSION", "RULE_SET_V1"),
    )


def _collect_failure_types(*results: ServiceResult) -> list[FailureType]:
    return [result.failure_type for result in results if result.failure_type is not None]


def _extract_credit_score(result: ServiceResult) -> int | None:
    if result.fallback_used and result.failure_type in {FailureType.TIMEOUT, FailureType.SERVICE_DOWN}:
        return None
    if result.data and "credit_score" in result.data:
        return int(result.data["credit_score"])
    return None


def _extract_income_stability(result: ServiceResult) -> float | None:
    if result.data and "income_stability" in result.data:
        return float(result.data["income_stability"])
    return None


def _extract_gst_compliance(result: ServiceResult) -> bool | None:
    if result.data and "gst_compliant" in result.data:
        return bool(result.data["gst_compliant"])
    return False if result.failure_type in {FailureType.PAN_MISMATCH, FailureType.NO_RECORD} else None

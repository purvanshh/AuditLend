import os
from dataclasses import asdict, dataclass
from typing import Any

from engine.confidence import compute_confidence
from engine.rules import Decision, evaluate
from services import FailureType, ServiceResult


@dataclass(frozen=True)
class DecisionOutput:
    decision: Decision
    confidence: float
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
    Orchestrates extraction, rules, confidence degradation, and manual review override.
    This function is deterministic and side-effect free.
    """
    monthly_income = float(user_data["monthly_income"])
    existing_emis = float(user_data.get("existing_emis", 0))
    dti = existing_emis / monthly_income

    credit_score = _extract_credit_score(credit_result)
    income_stability = _extract_income_stability(bank_result)
    gst_compliant = _extract_gst_compliance(gst_result)

    failure_types = _collect_failure_types(credit_result, bank_result, gst_result)
    used_fallback_credit = credit_result.fallback_used and credit_score == 600

    source_overrides = {
        "credit_score": "fallback" if used_fallback_credit else "live",
        "income_stability": _bank_source(bank_result),
        "gst_compliant": _gst_source(gst_result),
    }

    decision, factors = evaluate(
        credit_score,
        income_stability,
        dti,
        gst_compliant,
        failure_types,
        source_overrides=source_overrides,
    )
    confidence, penalty_reasons = compute_confidence(failure_types, used_fallback_credit)

    requires_manual_review = confidence < confidence_threshold
    if requires_manual_review:
        decision = Decision.NEEDS_REVIEW
        factors.append("Confidence below threshold - routed to manual review")

    return DecisionOutput(
        decision=decision,
        confidence=confidence,
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
    if result.data and "credit_score" in result.data:
        return int(result.data["credit_score"])
    return 600 if result.fallback_used else None


def _extract_income_stability(result: ServiceResult) -> float | None:
    if result.data and "income_stability" in result.data:
        return float(result.data["income_stability"])
    return 0.5 if result.failure_type in {FailureType.PARTIAL_DATA, FailureType.FORMAT_ERROR} else None


def _extract_gst_compliance(result: ServiceResult) -> bool | None:
    if result.data and "gst_compliant" in result.data:
        return bool(result.data["gst_compliant"])
    return False if result.failure_type in {FailureType.PAN_MISMATCH, FailureType.NO_RECORD} else None


def _bank_source(result: ServiceResult) -> str:
    if result.failure_type == FailureType.PARTIAL_DATA:
        return "partial"
    if result.fallback_used or result.failure_type == FailureType.FORMAT_ERROR:
        return "default"
    return "live"


def _gst_source(result: ServiceResult) -> str:
    if result.failure_type in {FailureType.PAN_MISMATCH, FailureType.NO_RECORD}:
        return "fallback"
    return "live"

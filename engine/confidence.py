from engine.rules import Decision
from services import FailureType


PENALTIES = {
    FailureType.TIMEOUT: 0.30,
    FailureType.STALE_DATA: 0.20,
    FailureType.SERVICE_DOWN: 0.30,
    FailureType.PARTIAL_DATA: 0.20,
    FailureType.FORMAT_ERROR: 0.30,
    FailureType.PAN_MISMATCH: 0.20,
    FailureType.NO_RECORD: 0.10,
}

FALLBACK_CREDIT_PENALTY = 0.10


def compute_data_reliability(
    failure_types: list[FailureType],
    used_fallback_credit: bool,
) -> tuple[float, list[str]]:
    """
    Pure function. Base reliability 1.0, subtracts deterministic data-quality penalties.
    Returns (data_reliability, list_of_penalty_descriptions).
    Final reliability is clamped to [0.0, 1.0].
    """
    data_reliability = 1.0
    penalty_reasons: list[str] = []

    for failure_type in failure_types:
        penalty = PENALTIES.get(failure_type, 0.0)
        data_reliability -= penalty
        penalty_reasons.append(f"{failure_type.value}: -{penalty:.2f}")

    if used_fallback_credit:
        data_reliability -= FALLBACK_CREDIT_PENALTY
        penalty_reasons.append(f"fallback_credit_score: -{FALLBACK_CREDIT_PENALTY:.2f}")

    return round(min(max(data_reliability, 0.0), 1.0), 2), penalty_reasons


def compute_decision_confidence(
    risk_score: float,
    decision: Decision,
    data_reliability: float,
    failure_types: list[FailureType],
) -> tuple[float, list[str]]:
    """
    True confidence = data_reliability * boundary_distance_factor.
    """
    boundary_factor = _boundary_distance_factor(risk_score, decision)
    confidence = round(min(max(data_reliability * boundary_factor, 0.0), 1.0), 2)
    reasons = [
        f"data_reliability: {data_reliability:.2f}",
        f"boundary_distance_factor: {boundary_factor:.2f}",
    ]
    if failure_types:
        reasons.append("failure_types: " + ", ".join(failure.value for failure in failure_types))
    return confidence, reasons


def compute_confidence(
    failure_types: list[FailureType],
    used_fallback_credit: bool,
) -> tuple[float, list[str]]:
    """Backward-compatible alias for the old data reliability calculation."""
    return compute_data_reliability(failure_types, used_fallback_credit)


def _boundary_distance_factor(risk_score: float, decision: Decision) -> float:
    if decision == Decision.APPROVE:
        if risk_score >= 80:
            return 1.0
        if risk_score >= 70:
            return 0.9
        if risk_score >= 55:
            return 0.7
        return 0.6

    if decision == Decision.DECLINE:
        if risk_score <= 20:
            return 1.0
        if risk_score <= 34:
            return 0.85
        return 0.75

    return 0.5

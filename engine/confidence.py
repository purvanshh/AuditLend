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


def compute_confidence(
    failure_types: list[FailureType],
    used_fallback_credit: bool,
) -> tuple[float, list[str]]:
    """
    Pure function. Base confidence 1.0, subtracts deterministic penalties.
    Returns (final_confidence, list_of_penalty_descriptions).
    Final confidence is clamped to [0.0, 1.0].
    """
    confidence = 1.0
    penalty_reasons: list[str] = []

    for failure_type in failure_types:
        penalty = PENALTIES.get(failure_type, 0.0)
        confidence -= penalty
        penalty_reasons.append(f"{failure_type.value}: -{penalty:.2f}")

    if used_fallback_credit:
        confidence -= FALLBACK_CREDIT_PENALTY
        penalty_reasons.append(f"fallback_credit_score: -{FALLBACK_CREDIT_PENALTY:.2f}")

    return round(min(max(confidence, 0.0), 1.0), 2), penalty_reasons

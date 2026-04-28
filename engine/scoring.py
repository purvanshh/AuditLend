import os

from services import FailureType


DEFAULT_CREDIT_SCORE = 600
DEFAULT_INCOME_STABILITY = 0.5


def compute_risk_score(
    credit_score: int | None,
    income_stability: float | None,
    dti: float,
    gst_compliant: bool | None,
    failure_types: list[FailureType],
) -> tuple[float, list[str]]:
    """
    Returns (risk_score, factor_breakdown).
    risk_score is 0-100 where higher = better.
    """
    credit_weight = _env_float("RISK_WEIGHT_CREDIT", 40.0)
    stability_weight = _env_float("RISK_WEIGHT_INCOME_STABILITY", 20.0)
    dti_weight = _env_float("RISK_WEIGHT_DTI", 25.0)
    gst_weight = _env_float("RISK_WEIGHT_GST", 15.0)
    data_quality_penalty = _env_float("RISK_DATA_QUALITY_PENALTY", 5.0)
    max_data_quality_penalty = _env_float("RISK_MAX_DATA_QUALITY_PENALTY", 15.0)

    effective_credit_score = DEFAULT_CREDIT_SCORE if credit_score is None else credit_score
    effective_stability = DEFAULT_INCOME_STABILITY if income_stability is None else income_stability

    credit_component = _clamp(effective_credit_score / 900, 0.0, 1.0) * credit_weight
    stability_component = _clamp(effective_stability, 0.0, 1.0) * stability_weight
    dti_component = max(0.0, 1 - dti) * dti_weight
    gst_component = gst_weight if gst_compliant is True else 0.0
    penalty = min(len(failure_types) * data_quality_penalty, max_data_quality_penalty)

    score = credit_component + stability_component + dti_component + gst_component - penalty
    risk_score = round(_clamp(score, 0.0, 100.0), 2)

    breakdown = [
        f"risk_score (computed) = {risk_score:.2f}",
        (
            f"credit_component ({_source_label(credit_score, 'fallback', 'live')}) = "
            f"{credit_component:.2f}/{credit_weight:.2f} (credit_score={effective_credit_score})"
        ),
        (
            f"income_stability_component ({_source_label(income_stability, 'default', 'live')}) = "
            f"{stability_component:.2f}/{stability_weight:.2f} "
            f"(income_stability={effective_stability:.2f})"
        ),
        f"dti_component (computed) = {dti_component:.2f}/{dti_weight:.2f} (dti={dti:.2f})",
        f"gst_component ({_gst_label(gst_compliant)}) = {gst_component:.2f}/{gst_weight:.2f}",
        f"data_quality_penalty (computed) = -{penalty:.2f}",
    ]
    return risk_score, breakdown


def _source_label(value: object | None, missing_label: str, present_label: str) -> str:
    return missing_label if value is None else present_label


def _gst_label(gst_compliant: bool | None) -> str:
    if gst_compliant is True:
        return "compliant"
    if gst_compliant is False:
        return "non_compliant"
    return "unknown"


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))

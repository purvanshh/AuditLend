from engine.rules import Decision
from engine.decision import compute_decision, compute_decision_from_env
from services import FailureType, ServiceResult


USER_DATA = {
    "monthly_income": 120000,
    "existing_emis": 25000,
    "loan_amount": 500000,
    "tenure_months": 36,
}


def result(data: dict | None, failure_type: FailureType | None = None, fallback_used: bool = False) -> ServiceResult:
    return ServiceResult(
        success=failure_type is None,
        data=data,
        failure_type=failure_type,
        raw_response=data,
        fallback_used=fallback_used,
    )


def test_high_quality_profile_is_approved_with_full_confidence() -> None:
    output = compute_decision(
        result({"credit_score": 800}),
        result({"income_stability": 0.9}),
        result({"gst_compliant": True}),
        USER_DATA,
    )

    assert output.decision == Decision.APPROVE
    assert output.confidence == 1.0
    assert output.data_reliability == 1.0
    assert output.risk_score == 88.35
    assert output.requires_manual_review is False


def test_credit_timeout_uses_fallback_score_and_manual_review_override() -> None:
    output = compute_decision(
        result({"credit_score": 600}, FailureType.TIMEOUT, fallback_used=True),
        result({"income_stability": 0.8}),
        result({"gst_compliant": True}),
        USER_DATA,
    )

    assert output.decision == Decision.NEEDS_REVIEW
    assert output.confidence == 0.54
    assert output.data_reliability == 0.6
    assert output.risk_score == 72.46
    assert output.requires_manual_review is True
    assert "fallback_credit_score: -0.10" in output.penalty_reasons
    assert "credit_component (fallback) = 26.67/40.00 (credit_score=600)" in output.factors


def test_low_confidence_overrides_high_rule_score_to_manual_review() -> None:
    output = compute_decision(
        result({"credit_score": 850}, FailureType.STALE_DATA),
        result({"monthly_inflow": 120000}, FailureType.PARTIAL_DATA),
        result({"gst_compliant": True}),
        USER_DATA,
    )

    assert output.decision == Decision.NEEDS_REVIEW
    assert output.data_reliability == 0.6
    assert output.confidence == 0.54
    assert output.requires_manual_review is True
    assert output.factors[-1] == "Confidence below threshold - routed to manual review"


def test_confidence_exactly_at_threshold_is_not_overridden() -> None:
    output = compute_decision(
        result({"credit_score": 900}, FailureType.STALE_DATA),
        result({"income_stability": 1.0}, FailureType.PARTIAL_DATA),
        result({"gst_compliant": True}),
        {"monthly_income": 120000, "existing_emis": 0, "loan_amount": 500000, "tenure_months": 36},
        confidence_threshold=0.6,
    )

    assert output.confidence == 0.6
    assert output.requires_manual_review is False


def test_high_dti_declines_when_confidence_is_high_enough() -> None:
    output = compute_decision(
        result({"credit_score": 300}),
        result({"income_stability": 0.0}),
        result({"gst_compliant": True}),
        {"monthly_income": 120000, "existing_emis": 84000, "loan_amount": 500000, "tenure_months": 36},
    )

    assert output.decision == Decision.DECLINE
    assert output.confidence == 0.75


def test_partial_bank_data_uses_neutral_stability() -> None:
    output = compute_decision(
        result({"credit_score": 700}),
        result({"monthly_inflow": 120000}, FailureType.PARTIAL_DATA),
        result({"gst_compliant": True}),
        USER_DATA,
    )

    assert output.decision == Decision.APPROVE
    assert "income_stability_component (default) = 10.00/20.00 (income_stability=0.50)" in output.factors
    assert output.data_reliability == 0.8
    assert output.confidence == 0.72


def test_decision_output_serializes_enum_values() -> None:
    output = compute_decision(
        result({"credit_score": 800}),
        result({"income_stability": 0.9}),
        result({"gst_compliant": True}),
        USER_DATA,
    )

    assert output.to_dict()["decision"] == "APPROVE"
    assert output.to_dict()["risk_score"] == 88.35
    assert output.to_dict()["data_reliability"] == 1.0


def test_env_wrapper_uses_configured_threshold_and_active_rule_set(monkeypatch) -> None:
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.95")

    output = compute_decision_from_env(
        result({"credit_score": 800}),
        result({"income_stability": 0.9}),
        result({"gst_compliant": True}),
        USER_DATA,
    )

    assert output.rule_version == "RULE_SET_V1"
    assert output.requires_manual_review is False


def test_missing_credit_without_fallback_uses_default_source() -> None:
    output = compute_decision(
        result(None),
        result({"income_stability": 0.9}),
        result({"gst_compliant": True}),
        USER_DATA,
    )

    assert "credit_component (fallback) = 26.67/40.00 (credit_score=600)" in output.factors
    assert output.risk_score == 79.46
    assert output.confidence == 0.9


def test_format_error_bank_data_uses_default_stability() -> None:
    output = compute_decision(
        result({"credit_score": 700}),
        result(None, FailureType.FORMAT_ERROR, fallback_used=True),
        result({"gst_compliant": True}),
        USER_DATA,
    )

    assert output.decision == Decision.APPROVE
    assert "income_stability_component (default) = 10.00/20.00 (income_stability=0.50)" in output.factors
    assert output.data_reliability == 0.7
    assert output.confidence == 0.63


def test_gst_no_record_defaults_to_non_compliant() -> None:
    output = compute_decision(
        result({"credit_score": 700}),
        result({"income_stability": 0.7}),
        result(None, FailureType.NO_RECORD, fallback_used=True),
        USER_DATA,
    )

    assert output.decision == Decision.NEEDS_REVIEW
    assert "gst_component (non_compliant) = 0.00/15.00" in output.factors
    assert "gst_gate (applied) = risk_score capped at 54.00" in output.factors

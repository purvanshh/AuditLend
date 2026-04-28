from engine.rule_sets import RuleSet
from engine.scoring import compute_risk_score
from services import FailureType


def test_maximum_possible_score_is_100() -> None:
    score, factors = compute_risk_score(900, 1.0, 0.0, True, [])

    assert score == 100.0
    assert factors[0] == "risk_score (computed) = 100.00"


def test_minimum_possible_score_clamps_to_zero() -> None:
    score, _ = compute_risk_score(
        300,
        0.0,
        1.0,
        False,
        [FailureType.TIMEOUT, FailureType.FORMAT_ERROR, FailureType.PAN_MISMATCH],
    )

    assert score == 0.0


def test_missing_credit_score_uses_conservative_fallback() -> None:
    score, factors = compute_risk_score(None, 0.5, 0.5, False, [])

    assert score == 49.17
    assert "credit_component (fallback) = 26.67/40.00 (credit_score=600)" in factors


def test_missing_income_stability_uses_neutral_default() -> None:
    score, factors = compute_risk_score(600, None, 0.5, False, [])

    assert score == 49.17
    assert "income_stability_component (default) = 10.00/20.00 (income_stability=0.50)" in factors


def test_unknown_gst_gets_no_points() -> None:
    unknown_score, factors = compute_risk_score(600, 0.5, 0.5, None, [])
    non_compliant_score, _ = compute_risk_score(600, 0.5, 0.5, False, [])

    assert unknown_score == non_compliant_score
    assert "gst_component (unknown) = 0.00/15.00" in factors


def test_gst_compliance_adds_15_points() -> None:
    compliant_score, _ = compute_risk_score(600, 0.5, 0.5, True, [])
    non_compliant_score, _ = compute_risk_score(600, 0.5, 0.5, False, [])

    assert compliant_score - non_compliant_score == 15.0


def test_single_failure_applies_five_point_penalty() -> None:
    clean_score, _ = compute_risk_score(700, 0.7, 0.3, True, [])
    degraded_score, factors = compute_risk_score(700, 0.7, 0.3, True, [FailureType.STALE_DATA])

    assert clean_score - degraded_score == 5.0
    assert "data_quality_penalty (computed) = -5.00" in factors


def test_data_quality_penalty_is_capped_at_15_points() -> None:
    score, factors = compute_risk_score(
        700,
        0.7,
        0.3,
        True,
        [
            FailureType.TIMEOUT,
            FailureType.SERVICE_DOWN,
            FailureType.PARTIAL_DATA,
            FailureType.FORMAT_ERROR,
        ],
    )

    assert score == 62.61
    assert "data_quality_penalty (computed) = -15.00" in factors


def test_dti_component_never_goes_negative() -> None:
    score, factors = compute_risk_score(600, 0.5, 1.5, False, [])

    assert score == 36.67
    assert "dti_component (computed) = 0.00/25.00 (dti=1.50)" in factors


def test_credit_component_clamps_above_900() -> None:
    score, factors = compute_risk_score(950, 0.0, 1.0, False, [])

    assert score == 40.0
    assert "credit_component (live) = 40.00/40.00 (credit_score=950)" in factors


def test_income_stability_component_clamps_above_one() -> None:
    score, factors = compute_risk_score(0, 1.2, 1.0, False, [])

    assert score == 20.0
    assert "income_stability_component (live) = 20.00/20.00 (income_stability=1.20)" in factors


def test_weights_are_configurable_by_rule_set() -> None:
    rule_set = RuleSet(
        version="RULE_SET_TEST",
        description="Test weights",
        created_at="2026-04-29",
        credit_weight=50.0,
        stability_weight=10.0,
        dti_weight=25.0,
        gst_weight=15.0,
        data_quality_penalty=5.0,
        max_data_quality_penalty=15.0,
        approve_high_threshold=70.0,
        approve_moderate_threshold=55.0,
        decline_threshold=35.0,
        moderate_max_dti=0.5,
        decline_dti_threshold=0.6,
    )

    score, _ = compute_risk_score(900, 1.0, 0.0, True, [], rule_set)

    assert score == 100.0

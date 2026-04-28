from engine.confidence import compute_decision_confidence
from engine.rules import Decision
from services import FailureType


def test_high_approve_score_with_reliable_data_has_high_confidence() -> None:
    confidence, reasons = compute_decision_confidence(85, Decision.APPROVE, 1.0, [])

    assert confidence == 1.0
    assert "boundary_distance_factor: 1.00" in reasons


def test_approve_score_in_70s_gets_ninety_percent_boundary_factor() -> None:
    confidence, _ = compute_decision_confidence(75, Decision.APPROVE, 1.0, [])

    assert confidence == 0.9


def test_borderline_approve_score_gets_moderate_confidence_even_with_perfect_data() -> None:
    confidence, _ = compute_decision_confidence(60, Decision.APPROVE, 1.0, [])

    assert confidence == 0.7


def test_high_score_with_low_data_reliability_triggers_low_confidence() -> None:
    confidence, reasons = compute_decision_confidence(
        85,
        Decision.APPROVE,
        0.5,
        [FailureType.TIMEOUT, FailureType.PARTIAL_DATA],
    )

    assert confidence == 0.5
    assert "failure_types: TIMEOUT, PARTIAL_DATA" in reasons


def test_clear_decline_has_high_confidence_when_score_is_very_low() -> None:
    confidence, _ = compute_decision_confidence(20, Decision.DECLINE, 1.0, [])

    assert confidence == 1.0


def test_decline_near_boundary_gets_reduced_confidence() -> None:
    confidence, _ = compute_decision_confidence(30, Decision.DECLINE, 1.0, [])

    assert confidence == 0.85


def test_needs_review_always_gets_half_boundary_factor() -> None:
    confidence, _ = compute_decision_confidence(50, Decision.NEEDS_REVIEW, 1.0, [])

    assert confidence == 0.5

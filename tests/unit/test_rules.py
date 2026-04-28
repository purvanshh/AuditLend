import pytest

from engine.rules import Decision, evaluate
from services import FailureType


@pytest.mark.parametrize(
    ("risk_score", "credit_score", "dti", "failures", "gst", "expected"),
    [
        (80, 800, 0.2, [], True, Decision.APPROVE),
        (70, 750, 0.49, [], True, Decision.APPROVE),
        (69, 700, 0.49, [], True, Decision.APPROVE),
        (55, 650, 0.49, [], True, Decision.APPROVE),
        (55, 650, 0.50, [], True, Decision.NEEDS_REVIEW),
        (34.99, 500, 0.2, [], True, Decision.DECLINE),
        (40, 700, 0.61, [], True, Decision.DECLINE),
        (35, 700, 0.60, [], True, Decision.NEEDS_REVIEW),
        (54.99, 650, 0.2, [], True, Decision.NEEDS_REVIEW),
        (80, 800, 0.2, [FailureType.STALE_DATA], True, Decision.APPROVE),
        (100, 900, 0.0, [], False, Decision.NEEDS_REVIEW),
        (30, 300, 0.2, [], False, Decision.DECLINE),
        (55, None, 0.49, [], None, Decision.APPROVE),
    ],
)
def test_rule_matrix(
    risk_score: float,
    credit_score: int | None,
    dti: float,
    failures: list[FailureType],
    gst: bool | None,
    expected: Decision,
) -> None:
    decision, factors = evaluate(risk_score, credit_score, dti, failures, gst)

    assert decision == expected
    assert any(factor.startswith("risk_score") for factor in factors)
    assert any(factor.startswith("dti") for factor in factors)


def test_factor_strings_include_failure_types() -> None:
    _, factors = evaluate(70, 700, 0.3, [FailureType.TIMEOUT, FailureType.PARTIAL_DATA], True)

    assert "data_reliability_flags = TIMEOUT, PARTIAL_DATA" in factors


def test_gst_non_compliance_blocks_approval_even_with_perfect_score() -> None:
    decision, factors = evaluate(100, 900, 0.0, [], False)

    assert decision == Decision.NEEDS_REVIEW
    assert "gst_gate (applied) = risk_score capped at 54.00" in factors

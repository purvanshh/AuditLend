import pytest

from engine.rules import Decision, evaluate
from services import FailureType


@pytest.mark.parametrize(
    ("credit_score", "income_stability", "dti", "gst", "failures", "expected"),
    [
        (800, 0.9, 0.2, True, [], Decision.APPROVE),
        (750, 0.7, 0.39, True, [], Decision.APPROVE),
        (700, 0.6, 0.45, True, [], Decision.APPROVE),
        (650, 0.5, 0.49, True, [], Decision.APPROVE),
        (749, 0.7, 0.39, True, [], Decision.APPROVE),
        (800, 0.69, 0.3, True, [], Decision.APPROVE),
        (800, 0.9, 0.4, True, [], Decision.APPROVE),
        (550, 0.8, 0.3, True, [], Decision.DECLINE),
        (750, 0.8, 0.7, True, [], Decision.DECLINE),
        (599, 0.8, 0.2, True, [], Decision.DECLINE),
        (600, 0.8, 0.6, True, [], Decision.DECLINE),
        (601, 0.8, 0.59, True, [], Decision.NEEDS_REVIEW),
        (None, 0.9, 0.2, True, [], Decision.NEEDS_REVIEW),
        (700, None, 0.3, True, [], Decision.APPROVE),
        (None, None, 0.7, None, [], Decision.DECLINE),
        (800, 0.9, 0.2, True, [FailureType.STALE_DATA], Decision.APPROVE),
        (800, 0.4, 0.2, True, [], Decision.NEEDS_REVIEW),
        (640, 0.9, 0.2, True, [], Decision.NEEDS_REVIEW),
        (700, 0.6, 0.5, True, [], Decision.NEEDS_REVIEW),
        (900, 1.0, 0.0, False, [], Decision.APPROVE),
    ],
)
def test_rule_matrix(
    credit_score: int | None,
    income_stability: float | None,
    dti: float,
    gst: bool | None,
    failures: list[FailureType],
    expected: Decision,
) -> None:
    decision, factors = evaluate(credit_score, income_stability, dti, gst, failures)

    assert decision == expected
    assert any(factor.startswith("credit_score") for factor in factors)
    assert any(factor.startswith("dti") for factor in factors)


def test_factor_strings_include_failure_types() -> None:
    _, factors = evaluate(700, 0.6, 0.3, True, [FailureType.TIMEOUT, FailureType.PARTIAL_DATA])

    assert "data_reliability_flags = TIMEOUT, PARTIAL_DATA" in factors

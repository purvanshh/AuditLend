from engine.confidence import compute_data_reliability
from services import FailureType


def test_no_failures_has_full_data_reliability() -> None:
    assert compute_data_reliability([], used_fallback_credit=False) == (1.0, [])


def test_single_timeout_penalty() -> None:
    data_reliability, reasons = compute_data_reliability([FailureType.TIMEOUT], used_fallback_credit=False)
    assert data_reliability == 0.70
    assert reasons == ["TIMEOUT: -0.30"]


def test_timeout_plus_partial_data_penalty() -> None:
    data_reliability, _ = compute_data_reliability(
        [FailureType.TIMEOUT, FailureType.PARTIAL_DATA],
        used_fallback_credit=False,
    )
    assert data_reliability == 0.50


def test_stale_data_plus_pan_mismatch_penalty() -> None:
    data_reliability, _ = compute_data_reliability(
        [FailureType.STALE_DATA, FailureType.PAN_MISMATCH],
        used_fallback_credit=False,
    )
    assert data_reliability == 0.60


def test_all_three_services_fail_clamps_data_reliability() -> None:
    data_reliability, _ = compute_data_reliability(
        [FailureType.TIMEOUT, FailureType.FORMAT_ERROR, FailureType.PAN_MISMATCH],
        used_fallback_credit=True,
    )
    assert data_reliability == 0.10


def test_fallback_credit_penalty_adds_extra_penalty() -> None:
    data_reliability, reasons = compute_data_reliability([], used_fallback_credit=True)
    assert data_reliability == 0.90
    assert reasons == ["fallback_credit_score: -0.10"]


def test_full_combination_matches_documented_formula() -> None:
    data_reliability, _ = compute_data_reliability(
        [FailureType.TIMEOUT, FailureType.PARTIAL_DATA, FailureType.PAN_MISMATCH],
        used_fallback_credit=True,
    )
    assert data_reliability == 0.20


def test_penalties_clamped_to_zero() -> None:
    data_reliability, _ = compute_data_reliability(
        [
            FailureType.TIMEOUT,
            FailureType.SERVICE_DOWN,
            FailureType.FORMAT_ERROR,
            FailureType.PAN_MISMATCH,
            FailureType.PARTIAL_DATA,
        ],
        used_fallback_credit=True,
    )
    assert data_reliability == 0.0

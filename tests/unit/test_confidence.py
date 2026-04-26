from engine.confidence import compute_confidence
from services import FailureType


def test_no_failures_has_full_confidence() -> None:
    assert compute_confidence([], used_fallback_credit=False) == (1.0, [])


def test_single_timeout_penalty() -> None:
    confidence, reasons = compute_confidence([FailureType.TIMEOUT], used_fallback_credit=False)
    assert confidence == 0.70
    assert reasons == ["TIMEOUT: -0.30"]


def test_timeout_plus_partial_data_penalty() -> None:
    confidence, _ = compute_confidence(
        [FailureType.TIMEOUT, FailureType.PARTIAL_DATA],
        used_fallback_credit=False,
    )
    assert confidence == 0.50


def test_stale_data_plus_pan_mismatch_penalty() -> None:
    confidence, _ = compute_confidence(
        [FailureType.STALE_DATA, FailureType.PAN_MISMATCH],
        used_fallback_credit=False,
    )
    assert confidence == 0.60


def test_all_three_services_fail_clamps_confidence() -> None:
    confidence, _ = compute_confidence(
        [FailureType.TIMEOUT, FailureType.FORMAT_ERROR, FailureType.PAN_MISMATCH],
        used_fallback_credit=True,
    )
    assert confidence == 0.10


def test_fallback_credit_penalty_adds_extra_penalty() -> None:
    confidence, reasons = compute_confidence([], used_fallback_credit=True)
    assert confidence == 0.90
    assert reasons == ["fallback_credit_score: -0.10"]


def test_full_combination_matches_documented_formula() -> None:
    confidence, _ = compute_confidence(
        [FailureType.TIMEOUT, FailureType.PARTIAL_DATA, FailureType.PAN_MISMATCH],
        used_fallback_credit=True,
    )
    assert confidence == 0.20


def test_penalties_clamped_to_zero() -> None:
    confidence, _ = compute_confidence(
        [
            FailureType.TIMEOUT,
            FailureType.SERVICE_DOWN,
            FailureType.FORMAT_ERROR,
            FailureType.PAN_MISMATCH,
            FailureType.PARTIAL_DATA,
        ],
        used_fallback_credit=True,
    )
    assert confidence == 0.0

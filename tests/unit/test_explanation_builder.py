from datetime import UTC, datetime

from engine.explanation_builder import build_explanation
from models.audit_log import AuditLog


def test_build_explanation_from_degraded_audit_trail() -> None:
    entries = [
        AuditLog(
            step="CREDIT_BUREAU_FETCH",
            error_type="TIMEOUT",
            fallback_used=True,
            created_at=datetime(2026, 4, 26, tzinfo=UTC),
        ),
        AuditLog(
            step="DECISION_CALCULATION",
            output_snapshot={
                "decision": "NEEDS_REVIEW",
                "confidence": 0.5,
                "factors": [
                    "credit_score (fallback) = 600",
                    "income_stability (live) = 0.8",
                    "dti (computed) = 0.25",
                    "Confidence below threshold — routed to manual review",
                ],
                "rule_version": "RULE_SET_V1",
            },
            created_at=datetime(2026, 4, 26, tzinfo=UTC),
        ),
    ]

    explanation = build_explanation(entries, entries[-1].output_snapshot)

    assert explanation["decision"] == "NEEDS_REVIEW"
    assert "insufficient reliable data" in explanation["summary"]
    assert explanation["factors"][0] == {
        "name": "Credit Score",
        "value": "600",
        "status": "fallback",
    }
    assert explanation["timeline"][0]["status"] == "TIMEOUT"

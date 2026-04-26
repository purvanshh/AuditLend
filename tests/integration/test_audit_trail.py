import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.application import LoanApplication
from models.audit_log import AuditLog
from services.audit import write_audit_entry


def test_audit_log_entries_capture_each_step_with_snapshots(clean_database) -> None:
    application_id = uuid.uuid4()
    with Session(clean_database) as session:
        session.add(
            LoanApplication(
                id=application_id,
                idempotency_key="audit-001",
                user_data={"pan": "ABCDE1234F", "monthly_income": 120000, "existing_emis": 25000},
                status="COMPLETED",
                decision="APPROVE",
                confidence=Decimal("1.00"),
            )
        )
        session.flush()

        for step in ["CREDIT_BUREAU_FETCH", "BANK_ANALYZER_FETCH", "GST_VERIFIER_FETCH"]:
            write_audit_entry(
                application_id=application_id,
                step=step,
                input_snapshot={"fail_mode": "SUCCESS"},
                output_snapshot={"success": True},
                session=session,
            )
        write_audit_entry(
            application_id=application_id,
            step="DECISION_CALCULATION",
            input_snapshot={"user_data": {"pan": "***REDACTED***"}},
            output_snapshot={"decision": "APPROVE", "confidence": 1.0, "factors": [], "rule_version": "RULE_SET_V1"},
            rule_version="RULE_SET_V1",
            session=session,
        )
        session.commit()

    with Session(clean_database) as session:
        entries = session.scalars(
            select(AuditLog).where(AuditLog.application_id == application_id).order_by(AuditLog.id)
        ).all()

    assert [entry.step for entry in entries] == [
        "CREDIT_BUREAU_FETCH",
        "BANK_ANALYZER_FETCH",
        "GST_VERIFIER_FETCH",
        "DECISION_CALCULATION",
    ]
    assert all(entry.input_snapshot is not None for entry in entries)
    assert all(entry.output_snapshot is not None for entry in entries)
    assert all(entry.fallback_used is False for entry in entries[:3])


def test_explanation_endpoint_reads_from_audit_trail(api_client, clean_database) -> None:
    application_id = uuid.uuid4()
    with Session(clean_database) as session:
        session.add(
            LoanApplication(
                id=application_id,
                idempotency_key="explain-001",
                user_data={"pan": "ABCDE1234F", "monthly_income": 120000, "existing_emis": 25000},
                status="MANUAL_REVIEW",
                decision="NEEDS_REVIEW",
                confidence=Decimal("0.50"),
            )
        )
        session.flush()
        write_audit_entry(
            application_id=application_id,
            step="CREDIT_BUREAU_FETCH",
            input_snapshot={"fail_mode": "TIMEOUT"},
            output_snapshot={"success": False, "data": {"credit_score": 600}},
            error_type="TIMEOUT",
            fallback_used=True,
            fallback_reason="TIMEOUT",
            session=session,
        )
        write_audit_entry(
            application_id=application_id,
            step="DECISION_CALCULATION",
            input_snapshot={"user_data": {"pan": "***REDACTED***"}},
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
            rule_version="RULE_SET_V1",
            session=session,
        )
        session.commit()

    response = api_client.get(f"/api/v1/explanation/{application_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "NEEDS_REVIEW"
    assert "insufficient reliable data" in body["summary"]
    assert body["timeline"][0]["step"] == "CREDIT_BUREAU_FETCH"

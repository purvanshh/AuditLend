from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from db.session import get_sync_session
from models.audit_log import AuditLog


PII_KEYS = {
    "name",
    "pan",
    "pan_hash",
    "monthly_income",
    "existing_emis",
    "loan_amount",
    "monthly_inflow",
    "monthly_outflow",
    "average_balance",
    "annual_turnover",
    "bank_statement",
}


def write_audit_entry(
    application_id: str | UUID,
    step: str,
    input_snapshot: dict[str, Any] | None = None,
    output_snapshot: dict[str, Any] | None = None,
    error_type: str | None = None,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
    rule_version: str | None = None,
    actor: str = "system",
    *,
    session: Session | None = None,
) -> None:
    """Append-only insert to audit_logs table."""
    entry = AuditLog(
        application_id=application_id,
        step=step,
        input_snapshot=sanitize_audit_snapshot(input_snapshot),
        output_snapshot=sanitize_audit_snapshot(output_snapshot),
        error_type=error_type,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        rule_version=rule_version,
        actor=actor,
    )

    if session is not None:
        session.add(entry)
        return

    with get_sync_session() as managed_session:
        managed_session.add(entry)


def audit_safe_features(user_data: dict[str, Any], risk_score_breakdown: dict[str, Any]) -> dict[str, Any]:
    """
    Return a PII-free feature summary for audit logging.
    Raw identifiers, raw income, raw loan amounts, EMIs, and bank statement
    contents are intentionally omitted.
    """
    monthly_income = float(user_data.get("monthly_income") or 0)
    loan_amount = float(user_data.get("loan_amount") or 0)

    return {
        "dti": risk_score_breakdown.get("dti"),
        "income_band": _income_band(monthly_income),
        "loan_amount_band": _amount_band(loan_amount),
        "tenure_months": user_data.get("tenure_months"),
        "has_bank_statement": bool(user_data.get("bank_statement")),
        "risk_score_components": risk_score_breakdown.get("components", {}),
        "failure_types": risk_score_breakdown.get("failure_types", []),
    }


def sanitize_audit_snapshot(snapshot: Any) -> Any:
    """Recursively remove raw PII from snapshots before persistence."""
    if snapshot is None:
        return None
    if isinstance(snapshot, dict):
        sanitized: dict[str, Any] = {}
        for key, value in snapshot.items():
            if key in PII_KEYS:
                sanitized[key] = _safe_value_for_key(key, value)
            else:
                sanitized[key] = sanitize_audit_snapshot(value)
        return sanitized
    if isinstance(snapshot, list):
        return [sanitize_audit_snapshot(item) for item in snapshot]
    return snapshot


def _safe_value_for_key(key: str, value: Any) -> Any:
    if key in {"monthly_income", "monthly_inflow"}:
        numeric_value = _coerce_float(value)
        return _income_band(numeric_value) if numeric_value is not None else "***REDACTED***"
    if key in {"loan_amount", "monthly_outflow", "average_balance", "annual_turnover"}:
        numeric_value = _coerce_float(value)
        return _amount_band(numeric_value) if numeric_value is not None else "***REDACTED***"
    if key in {"existing_emis", "bank_statement"}:
        return "***REDACTED***"
    return "***REDACTED***"


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return None


def _income_band(income: float) -> str:
    if income <= 0:
        return "UNKNOWN"
    if income < 25_000:
        return "0-25K"
    if income < 50_000:
        return "25K-50K"
    if income < 100_000:
        return "50K-1L"
    if income < 200_000:
        return "1L-2L"
    return "2L+"


def _amount_band(amount: float) -> str:
    if amount <= 0:
        return "UNKNOWN"
    if amount < 100_000:
        return "0-1L"
    if amount < 500_000:
        return "1L-5L"
    if amount < 1_000_000:
        return "5L-10L"
    return "10L+"

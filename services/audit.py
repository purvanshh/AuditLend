from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from db.session import get_sync_session
from models.audit_log import AuditLog


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
        input_snapshot=input_snapshot,
        output_snapshot=output_snapshot,
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

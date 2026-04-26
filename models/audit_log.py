from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.base import Base


class AuditLog(Base):
    """APPEND ONLY — NEVER UPDATE OR DELETE ROWS IN THIS TABLE.
    This is the compliance-grade audit trail. Every decision step is
    recorded immutably. Tampering with this table is a regulatory violation.
    """

    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id"),
        nullable=False,
    )
    step = Column(String(100), nullable=False)
    input_snapshot = Column(JSONB, nullable=True)
    output_snapshot = Column(JSONB, nullable=True)
    error_type = Column(String(50), nullable=True)
    fallback_used = Column(Boolean, default=False, server_default=text("false"))
    fallback_reason = Column(Text, nullable=True)
    rule_version = Column(String(20), nullable=True)
    actor = Column(String(30), nullable=False, default="system", server_default=text("'system'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("idx_audit_app_step", "application_id", "created_at"),
    )

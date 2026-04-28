import uuid

from sqlalchemy import Column, DateTime, Index, LargeBinary, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.base import Base


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    idempotency_key = Column(String(255), nullable=False)
    pan_hash = Column(String(64), nullable=False)
    encrypted_user_data = Column(LargeBinary, nullable=False)
    encryption_nonce = Column(LargeBinary, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    decision = Column(String(30), nullable=True)
    confidence = Column(Numeric(3, 2), nullable=True)
    failure_flags = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    __table_args__ = (
        Index("idx_loan_status", "status"),
        Index("idx_loan_idempotency", "idempotency_key"),
        Index("idx_loan_pan_hash", "pan_hash"),
    )

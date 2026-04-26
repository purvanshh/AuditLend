from sqlalchemy import Column, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.base import Base


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    key = Column(String(255), primary_key=True)
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id"),
        nullable=False,
    )
    response = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.base import Base


class ExternalData(Base):
    __tablename__ = "external_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id"),
        nullable=False,
    )
    source_type = Column(String(30), nullable=False)
    request_params = Column(JSONB, nullable=True)
    response_data = Column(JSONB, nullable=True)
    failure_type = Column(String(30), nullable=True)
    idempotency_key = Column(String(255), nullable=False)
    fetched_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("idx_external_data_app", "application_id", "source_type"),
    )

from sqlalchemy import BigInteger, Column, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB

from db.base import Base


class OutboxMessage(Base):
    __tablename__ = "outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_name = Column(String(255), nullable=False)
    task_args = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    processed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_outbox_status_created", "status", "created_at"),
    )

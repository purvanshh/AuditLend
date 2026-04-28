"""add transactional outbox and external data uniqueness

Revision ID: 20260429_0004
Revises: 20260429_0003
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260429_0004"
down_revision: str | Sequence[str] | None = "20260429_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("task_args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_outbox_status_created", "outbox", ["status", "created_at"], unique=False)
    op.create_index(
        "uq_external_data_application_source",
        "external_data",
        ["application_id", "source_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_external_data_application_source", table_name="external_data")
    op.drop_index("idx_outbox_status_created", table_name="outbox")
    op.drop_table("outbox")

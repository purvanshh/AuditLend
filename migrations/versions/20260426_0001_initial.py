"""initial

Revision ID: 20260426_0001
Revises:
Create Date: 2026-04-26 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260426_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.create_table(
        "loan_applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("user_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("failure_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_loan_idempotency", "loan_applications", ["idempotency_key"], unique=False)
    op.create_index("idx_loan_status", "loan_applications", ["status"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step", sa.String(length=100), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_type", sa.String(length=50), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("rule_version", sa.String(length=20), nullable=True),
        sa.Column("actor", sa.String(length=30), server_default=sa.text("'system'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["loan_applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_app_step", "audit_logs", ["application_id", "created_at"], unique=False)

    op.create_table(
        "external_data",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("request_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("failure_type", sa.String(length=30), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["loan_applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_external_data_app", "external_data", ["application_id", "source_type"], unique=False)

    op.create_table(
        "idempotency_records",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["loan_applications.id"]),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_index("idx_external_data_app", table_name="external_data")
    op.drop_table("external_data")
    op.drop_index("idx_audit_app_step", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("idx_loan_status", table_name="loan_applications")
    op.drop_index("idx_loan_idempotency", table_name="loan_applications")
    op.drop_table("loan_applications")

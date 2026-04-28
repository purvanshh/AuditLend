"""encrypt user data at rest

Revision ID: 20260429_0002
Revises: 20260426_0001
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260429_0002"
down_revision: str | Sequence[str] | None = "20260426_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("loan_applications", sa.Column("pan_hash", sa.String(length=64), nullable=True))
    op.add_column("loan_applications", sa.Column("encrypted_user_data", sa.LargeBinary(), nullable=True))
    op.add_column("loan_applications", sa.Column("encryption_nonce", sa.LargeBinary(), nullable=True))
    op.alter_column("loan_applications", "user_data", existing_type=postgresql.JSONB(), nullable=True)
    op.create_index("idx_loan_pan_hash", "loan_applications", ["pan_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_loan_pan_hash", table_name="loan_applications")
    op.alter_column("loan_applications", "user_data", existing_type=postgresql.JSONB(), nullable=False)
    op.drop_column("loan_applications", "encryption_nonce")
    op.drop_column("loan_applications", "encrypted_user_data")
    op.drop_column("loan_applications", "pan_hash")

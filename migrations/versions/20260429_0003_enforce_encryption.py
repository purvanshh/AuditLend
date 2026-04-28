"""enforce encrypted user data storage

Revision ID: 20260429_0003
Revises: 20260429_0002
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from services.crypto import PIIService


revision: str = "20260429_0003"
down_revision: str | Sequence[str] | None = "20260429_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("loan_applications")}

    if "user_data" in columns:
        rows = list(
            connection.execute(
                sa.text(
                    """
                    SELECT id, user_data
                    FROM loan_applications
                    WHERE encrypted_user_data IS NULL
                       OR encryption_nonce IS NULL
                       OR pan_hash IS NULL
                    """
                )
            ).mappings()
        )
        if rows:
            pii_service = PIIService()
            for row in rows:
                user_data = row["user_data"]
                if not isinstance(user_data, dict) or not user_data.get("pan"):
                    raise RuntimeError(
                        "Cannot backfill encrypted user data: legacy row has no PAN in user_data"
                    )
                ciphertext, nonce = pii_service.encrypt(user_data)
                connection.execute(
                    sa.text(
                        """
                        UPDATE loan_applications
                        SET pan_hash = :pan_hash,
                            encrypted_user_data = :encrypted_user_data,
                            encryption_nonce = :encryption_nonce,
                            user_data = NULL
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": row["id"],
                        "pan_hash": pii_service.hash_pan(user_data["pan"]),
                        "encrypted_user_data": ciphertext,
                        "encryption_nonce": nonce,
                    },
                )

        remaining = connection.scalar(
            sa.text(
                """
                SELECT count(*)
                FROM loan_applications
                WHERE encrypted_user_data IS NULL
                   OR encryption_nonce IS NULL
                   OR pan_hash IS NULL
                """
            )
        )
        if remaining:
            raise RuntimeError("Cannot enforce encryption while plaintext or incomplete rows remain")

    op.alter_column("loan_applications", "pan_hash", existing_type=sa.String(length=64), nullable=False)
    op.alter_column("loan_applications", "encrypted_user_data", existing_type=sa.LargeBinary(), nullable=False)
    op.alter_column("loan_applications", "encryption_nonce", existing_type=sa.LargeBinary(), nullable=False)
    if "user_data" in columns:
        op.drop_column("loan_applications", "user_data")


def downgrade() -> None:
    op.add_column("loan_applications", sa.Column("user_data", sa.JSON(), nullable=True))
    op.alter_column("loan_applications", "encryption_nonce", existing_type=sa.LargeBinary(), nullable=True)
    op.alter_column("loan_applications", "encrypted_user_data", existing_type=sa.LargeBinary(), nullable=True)
    op.alter_column("loan_applications", "pan_hash", existing_type=sa.String(length=64), nullable=True)

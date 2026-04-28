"""protect audit logs from mutation

Revision ID: 20260429_0005
Revises: 20260429_0004
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260429_0005"
down_revision: str | Sequence[str] | None = "20260429_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'audit_logs table is append-only. Updates and deletes are forbidden.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS audit_logs_no_mutation ON audit_logs;
        CREATE TRIGGER audit_logs_no_mutation
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_mutation();
        """
    )
    op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM auditlend;")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_mutation ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_mutation();")
    op.execute("GRANT UPDATE, DELETE ON audit_logs TO auditlend;")

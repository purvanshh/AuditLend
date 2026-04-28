import uuid

import pytest
from sqlalchemy import text


def test_audit_logs_reject_update_and_delete(clean_database) -> None:
    application_id = uuid.uuid4()
    with clean_database.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO loan_applications
                    (id, idempotency_key, pan_hash, encrypted_user_data, encryption_nonce, status)
                VALUES
                    (:id, :idempotency_key, :pan_hash, :encrypted_user_data, :encryption_nonce, 'PENDING')
                """
            ),
            {
                "id": str(application_id),
                "idempotency_key": f"audit-immutability-{application_id}",
                "pan_hash": "a" * 64,
                "encrypted_user_data": b"ciphertext",
                "encryption_nonce": b"nonce",
            },
        )
        audit_id = connection.scalar(
            text(
                """
                INSERT INTO audit_logs (application_id, step, input_snapshot, output_snapshot)
                VALUES (:id, 'TEST_STEP', '{}', '{}')
                RETURNING id
                """
            ),
            {"id": str(application_id)},
        )

    with pytest.raises(Exception, match="append-only"):
        with clean_database.begin() as connection:
            connection.execute(text("UPDATE audit_logs SET step = 'MUTATED' WHERE id = :id"), {"id": audit_id})

    with pytest.raises(Exception, match="append-only"):
        with clean_database.begin() as connection:
            connection.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": audit_id})

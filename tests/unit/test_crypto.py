from services.crypto import PIIService
from worker.tasks.process_application import _decision_user_data, _redact_user_data


KEY_HEX = "01" * 32
ZERO_KEY_HEX = "00" * 32
SALT = "unit-test-salt"


def test_same_pan_produces_same_hash(monkeypatch) -> None:
    monkeypatch.setenv("PII_ENCRYPTION_KEY", KEY_HEX)
    monkeypatch.setenv("PAN_HASH_SALT", SALT)
    service = PIIService()

    assert service.hash_pan("ABCDE1234F") == service.hash_pan("ABCDE1234F")


def test_different_pans_produce_different_hashes(monkeypatch) -> None:
    monkeypatch.setenv("PII_ENCRYPTION_KEY", KEY_HEX)
    monkeypatch.setenv("PAN_HASH_SALT", SALT)
    service = PIIService()

    assert service.hash_pan("ABCDE1234F") != service.hash_pan("AAAAA1111A")


def test_encrypt_decrypt_roundtrip(monkeypatch) -> None:
    monkeypatch.setenv("PII_ENCRYPTION_KEY", KEY_HEX)
    monkeypatch.setenv("PAN_HASH_SALT", SALT)
    service = PIIService()
    payload = {
        "name": "Jane Doe",
        "pan": "ABCDE1234F",
        "monthly_income": 120000,
        "existing_emis": 25000,
    }

    ciphertext, nonce = service.encrypt_pii(payload)
    decrypted = service.decrypt_pii(ciphertext, nonce)

    assert decrypted == payload
    assert b"ABCDE1234F" not in ciphertext
    assert len(nonce) == 12


def test_missing_encryption_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("PII_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("PAN_HASH_SALT", SALT)

    try:
        PIIService()
    except RuntimeError as exc:
        assert "PII_ENCRYPTION_KEY" in str(exc)
    else:
        raise AssertionError("PIIService should reject a missing encryption key")


def test_zero_encryption_key_raises(monkeypatch) -> None:
    monkeypatch.setenv("PII_ENCRYPTION_KEY", ZERO_KEY_HEX)
    monkeypatch.setenv("PAN_HASH_SALT", SALT)

    try:
        PIIService()
    except RuntimeError as exc:
        assert "insecure" in str(exc)
    else:
        raise AssertionError("PIIService should reject the zero encryption key")


def test_dev_default_salt_raises(monkeypatch) -> None:
    monkeypatch.setenv("PII_ENCRYPTION_KEY", KEY_HEX)
    monkeypatch.setenv("PAN_HASH_SALT", "auditlend-dev-salt-do-not-use-in-production")

    try:
        PIIService()
    except RuntimeError as exc:
        assert "PAN_HASH_SALT" in str(exc)
    else:
        raise AssertionError("PIIService should reject the dev default salt")


def test_audit_redaction_strips_raw_pan() -> None:
    redacted = _redact_user_data({"pan": "ABCDE1234F", "credit_score": 750})

    assert redacted["pan"] == "***REDACTED***"
    assert "ABCDE1234F" not in str(redacted)


def test_decision_user_data_replaces_pan_with_hash() -> None:
    safe = _decision_user_data(
        {"pan": "ABCDE1234F", "monthly_income": 120000, "existing_emis": 25000},
        "abc123",
    )

    assert "pan" not in safe
    assert safe["pan_hash"] == "abc123"

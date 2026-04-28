import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


INSECURE_ENCRYPTION_KEYS = {
    "0" * 64,
    "change-me-to-a-real-64-char-hex-string",
}

INSECURE_PAN_SALTS = {
    "auditlend-default-salt",
    "auditlend-dev-salt",
    "auditlend-dev-salt-do-not-use-in-production",
    "change-me-to-a-real-random-salt",
}


class PIIService:
    """Handles PII encryption and PAN hashing."""

    def __init__(self) -> None:
        encryption_key_hex = os.environ.get("PII_ENCRYPTION_KEY")
        if not encryption_key_hex:
            raise RuntimeError("PII_ENCRYPTION_KEY environment variable is required")
        if encryption_key_hex in INSECURE_ENCRYPTION_KEYS:
            raise RuntimeError("PII_ENCRYPTION_KEY is insecure. Generate a real 32-byte key.")
        try:
            encryption_key = bytes.fromhex(encryption_key_hex)
        except ValueError as exc:
            raise RuntimeError("PII_ENCRYPTION_KEY must be a 64-character hex string") from exc
        if len(encryption_key) != 32:
            raise RuntimeError("PII_ENCRYPTION_KEY must decode to 32 bytes for AES-256-GCM")

        pan_salt = os.environ.get("PAN_HASH_SALT")
        if not pan_salt:
            raise RuntimeError("PAN_HASH_SALT environment variable is required")
        if pan_salt in INSECURE_PAN_SALTS:
            raise RuntimeError("PAN_HASH_SALT is insecure. Generate a real per-environment salt.")

        self.aesgcm = AESGCM(encryption_key)
        self.pan_salt = pan_salt

    def hash_pan(self, pan: str) -> str:
        """SHA-256 hash with per-instance salt from env."""
        return hashlib.sha256(f"{pan}:{self.pan_salt}".encode("utf-8")).hexdigest()

    def encrypt(self, data: dict[str, Any]) -> tuple[bytes, bytes]:
        """Encrypt PII fields. Returns (ciphertext, nonce)."""
        plaintext = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, plaintext, None)
        return ciphertext, nonce

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> dict[str, Any]:
        """Decrypt PII fields."""
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
        payload = json.loads(plaintext.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Decrypted PII payload must be a JSON object")
        return payload

    def encrypt_pii(self, data: dict[str, Any]) -> tuple[bytes, bytes]:
        """Backward-compatible alias for older call sites."""
        return self.encrypt(data)

    def decrypt_pii(self, ciphertext: bytes, nonce: bytes) -> dict[str, Any]:
        """Backward-compatible alias for older call sites."""
        return self.decrypt(ciphertext, nonce)


def pii_service_from_env() -> PIIService:
    return PIIService()

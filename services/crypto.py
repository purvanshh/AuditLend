import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


DEFAULT_DEV_ENCRYPTION_KEY = bytes.fromhex(
    "00" * 32
)


class PIIService:
    """Handles PII encryption and PAN hashing."""

    def __init__(self, encryption_key: bytes):
        if len(encryption_key) not in {16, 24, 32}:
            raise ValueError("PII encryption key must be 16, 24, or 32 bytes")
        self.aesgcm = AESGCM(encryption_key)

    def hash_pan(self, pan: str) -> str:
        """SHA-256 hash with per-instance salt from env."""
        salt = os.environ.get("PAN_HASH_SALT", "auditlend-default-salt")
        return hashlib.sha256(f"{pan}:{salt}".encode("utf-8")).hexdigest()

    def encrypt_pii(self, data: dict[str, Any]) -> tuple[bytes, bytes]:
        """Encrypt PII fields. Returns (ciphertext, nonce)."""
        plaintext = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, plaintext, None)
        return ciphertext, nonce

    def decrypt_pii(self, ciphertext: bytes, nonce: bytes) -> dict[str, Any]:
        """Decrypt PII fields."""
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
        payload = json.loads(plaintext.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Decrypted PII payload must be a JSON object")
        return payload


def pii_service_from_env() -> PIIService:
    key_hex = os.environ.get("PII_ENCRYPTION_KEY")
    if not key_hex:
        return PIIService(DEFAULT_DEV_ENCRYPTION_KEY)
    return PIIService(bytes.fromhex(key_hex))

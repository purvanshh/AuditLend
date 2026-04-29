from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import pytest
import redis
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


TEST_DATABASE_URL = os.getenv(
    "AUDITLEND_TEST_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql://auditlend:auditlend@localhost:5432/auditlend"),
)
TEST_ASYNC_DATABASE_URL = os.getenv(
    "AUDITLEND_TEST_ASYNC_DATABASE_URL",
    os.getenv("ASYNC_DATABASE_URL", "postgresql+asyncpg://auditlend:auditlend@localhost:5432/auditlend"),
)
TEST_REDIS_URL = os.getenv(
    "AUDITLEND_TEST_REDIS_URL",
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)
TEST_PII_ENCRYPTION_KEY = "02468ace02468ace02468ace02468ace02468ace02468ace02468ace02468ace"
TEST_PAN_HASH_SALT = "test-salt-for-ci"

os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("ASYNC_DATABASE_URL", TEST_ASYNC_DATABASE_URL)
os.environ.setdefault("REDIS_URL", TEST_REDIS_URL)
os.environ.setdefault("PII_ENCRYPTION_KEY", TEST_PII_ENCRYPTION_KEY)
os.environ.setdefault("PAN_HASH_SALT", TEST_PAN_HASH_SALT)
os.environ.setdefault("API_KEYS", "test-api-key-for-ci:read-write")
os.environ.setdefault("AUDITLEND_ASYNC_DB_POOL", "null")


def _postgres_available() -> bool:
    try:
        engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture
def sample_user_data() -> dict[str, Any]:
    return {
        "name": "Jane Doe",
        "pan": "ABCDE1234F",
        "monthly_income": 120000,
        "existing_emis": 25000,
        "loan_amount": 500000,
        "tenure_months": 36,
    }


@pytest.fixture
def sample_apply_payload(sample_user_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "idempotency_key": "test-apply-001",
        "user_data": sample_user_data,
        "failure_flags": {
            "credit_bureau": "SUCCESS",
            "bank_analyzer": "SUCCESS",
            "gst_verifier": "SUCCESS",
        },
    }


@pytest.fixture(scope="session")
def postgres_engine() -> Generator[Engine, None, None]:
    if not _postgres_available():
        pytest.skip("PostgreSQL is not available; start docker compose or set AUDITLEND_TEST_DATABASE_URL")

    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def clean_database(postgres_engine: Engine) -> Generator[Engine, None, None]:
    _truncate_database(postgres_engine)
    _flush_redis()
    try:
        yield postgres_engine
    finally:
        _truncate_database(postgres_engine)
        _flush_redis()


@pytest.fixture
def api_client(clean_database: Engine, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from api.main import app

    monkeypatch.setenv("API_KEYS", "test-api-key-for-ci:read-write")
    client = TestClient(app)
    client.headers.update({"X-API-Key": "test-api-key-for-ci"})
    return client


def _truncate_database(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE audit_logs, external_data, idempotency_records, "
                "outbox, loan_applications RESTART IDENTITY CASCADE"
            )
        )


def _flush_redis() -> None:
    client = redis.Redis.from_url(TEST_REDIS_URL)
    try:
        client.flushdb()
    finally:
        client.close()


def encrypted_application_fields(user_data: dict[str, Any]) -> dict[str, Any]:
    from services.crypto import pii_service_from_env

    pii_service = pii_service_from_env()
    encrypted_user_data, encryption_nonce = pii_service.encrypt(user_data)
    return {
        "pan_hash": pii_service.hash_pan(user_data["pan"]),
        "encrypted_user_data": encrypted_user_data,
        "encryption_nonce": encryption_nonce,
    }

import hashlib
import json
import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
import redis.asyncio as redis_async
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_async_session
from api.schemas.application import ApplyLoanRequest, ApplyLoanResponse, StatusResponse
from models.application import LoanApplication
from models.idempotency import IdempotencyRecord
from services.crypto import pii_service_from_env
from services.metrics import loan_applications_total
from worker.tasks.process_application import process_application

router = APIRouter()
logger = structlog.get_logger()


@router.post("/apply-loan", response_model=ApplyLoanResponse, status_code=status.HTTP_201_CREATED)
async def apply_loan(
    request: ApplyLoanRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    idempotency_key_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ApplyLoanResponse:
    key = idempotency_key_header or request.idempotency_key
    payload_hash = _payload_hash(request, key)

    cached = await _redis_idempotency_get(key)
    if cached is not None:
        stored_hash = cached.get("_request_hash")
        if stored_hash != payload_hash:
            raise HTTPException(status_code=409, detail="Idempotency key reused with a different payload")
        response.status_code = status.HTTP_200_OK
        return ApplyLoanResponse(**cached["public"])

    existing = await session.get(IdempotencyRecord, key)
    if existing is not None:
        stored_hash = existing.response.get("_request_hash")
        if stored_hash != payload_hash:
            raise HTTPException(status_code=409, detail="Idempotency key reused with a different payload")
        await _redis_idempotency_set(key, existing.response)
        response.status_code = status.HTTP_200_OK
        return ApplyLoanResponse(**existing.response["public"])

    pii_service = pii_service_from_env()
    user_data = request.user_data.model_dump(mode="json")
    encrypted_user_data, encryption_nonce = pii_service.encrypt_pii(user_data)

    application = LoanApplication(
        idempotency_key=key,
        user_data=None,
        pan_hash=pii_service.hash_pan(request.user_data.pan),
        encrypted_user_data=encrypted_user_data,
        encryption_nonce=encryption_nonce,
        failure_flags=(request.failure_flags.model_dump(mode="json", exclude_none=True) if request.failure_flags else None),
        status="PENDING",
    )
    session.add(application)
    await session.flush()

    public_response = {
        "application_id": str(application.id),
        "status": application.status,
        "message": "Application received and queued for processing",
    }
    idempotency_response = {
        "public": public_response,
        "_request_hash": payload_hash,
    }
    insert_stmt = (
        pg_insert(IdempotencyRecord)
        .values(key=key, application_id=application.id, response=idempotency_response)
        .on_conflict_do_nothing(index_elements=["key"])
        .returning(IdempotencyRecord.key)
    )
    inserted_key = await session.scalar(insert_stmt)
    if inserted_key is None:
        await session.rollback()
        existing_after_race = await session.get(IdempotencyRecord, key)
        if existing_after_race is None:
            raise HTTPException(status_code=409, detail="Idempotency conflict could not be resolved")
        if existing_after_race.response.get("_request_hash") != payload_hash:
            raise HTTPException(status_code=409, detail="Idempotency key reused with a different payload")
        await _redis_idempotency_set(key, existing_after_race.response)
        response.status_code = status.HTTP_200_OK
        return ApplyLoanResponse(**existing_after_race.response["public"])

    await session.commit()
    await _redis_idempotency_set(key, idempotency_response)
    loan_applications_total.labels(status=application.status).inc()
    process_application.delay(str(application.id))
    return ApplyLoanResponse(**public_response)


@router.get("/status/{application_id}", response_model=StatusResponse)
async def get_status(
    application_id: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> StatusResponse:
    application = await session.get(LoanApplication, _application_uuid(application_id))
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return StatusResponse(
        application_id=str(application.id),
        status=application.status,
        updated_at=application.updated_at,
    )


def _payload_hash(request: ApplyLoanRequest, idempotency_key: str) -> str:
    payload = request.model_dump(mode="json")
    payload["idempotency_key"] = idempotency_key
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _application_uuid(application_id: str) -> UUID:
    try:
        return UUID(application_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Application not found") from exc


def _idempotency_cache_key(idempotency_key: str) -> str:
    return f"idempotent:{idempotency_key}"


async def _redis_idempotency_get(idempotency_key: str) -> dict | None:
    redis_client = redis_async.from_url(_redis_url(), decode_responses=True)
    try:
        cached = await redis_client.get(_idempotency_cache_key(idempotency_key))
    except Exception as exc:
        logger.warning("idempotency_redis_get_failed", error=str(exc))
        return None
    finally:
        await redis_client.aclose()

    if cached is None:
        return None
    try:
        payload = json.loads(cached)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def _redis_idempotency_set(idempotency_key: str, payload: dict) -> None:
    redis_client = redis_async.from_url(_redis_url(), decode_responses=True)
    try:
        await redis_client.setex(
            _idempotency_cache_key(idempotency_key),
            _idempotency_ttl_seconds(),
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
    except Exception as exc:
        logger.warning("idempotency_redis_set_failed", error=str(exc))
    finally:
        await redis_client.aclose()


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://redis:6379/0")


def _idempotency_ttl_seconds() -> int:
    return int(os.getenv("IDEMPOTENCY_CACHE_TTL_SECONDS", "86400"))

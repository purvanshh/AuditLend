import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_async_session
from api.schemas.application import ApplyLoanRequest, ApplyLoanResponse, StatusResponse
from models.application import LoanApplication
from models.idempotency import IdempotencyRecord
from worker.tasks.process_application import process_application

router = APIRouter()


@router.post("/apply-loan", response_model=ApplyLoanResponse, status_code=status.HTTP_201_CREATED)
async def apply_loan(
    request: ApplyLoanRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    idempotency_key_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ApplyLoanResponse:
    key = idempotency_key_header or request.idempotency_key
    payload_hash = _payload_hash(request, key)

    existing = await session.get(IdempotencyRecord, key)
    if existing is not None:
        stored_hash = existing.response.get("_request_hash")
        if stored_hash != payload_hash:
            raise HTTPException(status_code=409, detail="Idempotency key reused with a different payload")
        response.status_code = status.HTTP_200_OK
        return ApplyLoanResponse(**existing.response["public"])

    application = LoanApplication(
        idempotency_key=key,
        user_data=request.user_data.model_dump(mode="json"),
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
        response.status_code = status.HTTP_200_OK
        return ApplyLoanResponse(**existing_after_race.response["public"])

    await session.commit()
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

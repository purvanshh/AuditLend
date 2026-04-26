from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_async_session
from api.schemas.explanation import ExplanationResponse
from engine.explanation_builder import build_explanation
from models.application import LoanApplication
from models.audit_log import AuditLog

router = APIRouter()


@router.get("/explanation/{application_id}", response_model=ExplanationResponse)
async def get_explanation(
    application_id: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> ExplanationResponse | JSONResponse:
    app_uuid = _application_uuid(application_id)
    application = await session.get(LoanApplication, app_uuid)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    if application.status in {"PENDING", "PROCESSING"} or application.decision is None:
        return JSONResponse(
            status_code=202,
            content={"status": application.status, "message": "Explanation not yet available"},
        )

    audit_entries = list(
        (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.application_id == app_uuid)
                .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            )
        ).all()
    )
    decision_output = _final_decision_output(audit_entries)
    explanation = build_explanation(audit_entries, decision_output)
    return ExplanationResponse(application_id=str(application.id), **explanation)


def _final_decision_output(audit_entries: list[AuditLog]) -> dict:
    for entry in reversed(audit_entries):
        if entry.step == "DECISION_CALCULATION" and entry.output_snapshot:
            return entry.output_snapshot
    return {}


def _application_uuid(application_id: str) -> UUID:
    try:
        return UUID(application_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Application not found") from exc

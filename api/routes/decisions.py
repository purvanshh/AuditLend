from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_async_session
from api.schemas.decision import DecisionResponse
from models.application import LoanApplication
from models.audit_log import AuditLog

router = APIRouter()


@router.get("/decision/{application_id}", response_model=DecisionResponse)
async def get_decision(
    application_id: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> DecisionResponse | JSONResponse:
    app_uuid = _application_uuid(application_id)
    application = await session.get(LoanApplication, app_uuid)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    if application.status in {"PENDING", "PROCESSING"} or application.decision is None:
        return JSONResponse(
            status_code=202,
            content={"status": application.status, "message": "Decision not yet available"},
        )

    decision_output = await _decision_output(session, app_uuid)
    return DecisionResponse(
        application_id=str(application.id),
        decision=application.decision,
        confidence=float(application.confidence) if application.confidence is not None else None,
        data_reliability=decision_output.get("data_reliability"),
        risk_score=decision_output.get("risk_score"),
        factors=decision_output.get("factors", []),
        rule_version=decision_output.get("rule_version"),
    )


async def _decision_output(session: AsyncSession, application_id: UUID) -> dict:
    statement = (
        select(AuditLog)
        .where(AuditLog.application_id == application_id, AuditLog.step == "DECISION_CALCULATION")
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(1)
    )
    entry = await session.scalar(statement)
    return entry.output_snapshot if entry and entry.output_snapshot else {}


def _application_uuid(application_id: str) -> UUID:
    try:
        return UUID(application_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Application not found") from exc

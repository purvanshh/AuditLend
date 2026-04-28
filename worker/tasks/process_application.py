import asyncio
from collections.abc import Awaitable, Callable
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import redis.asyncio as redis_async
import structlog
from sqlalchemy import and_, or_, select, update

from db.session import get_sync_session
from engine.decision import DecisionOutput, compute_decision_from_env
from engine.rules import Decision
from models.application import LoanApplication
from models.external_data import ExternalData
from services import FailureType, ServiceResult
from services.audit import audit_safe_features, write_audit_entry
from services.bank_analyzer import BankAnalyzerService
from services.credit_bureau import CreditBureauService
from services.crypto import pii_service_from_env
from services.gst_verifier import GstVerifierService
from services.metrics import decision_confidence, loan_applications_total
from worker.celery_app import celery_app


logger = structlog.get_logger()


@celery_app.task(bind=True, max_retries=0)
def process_application(self, application_id: str) -> dict[str, Any]:
    """
    Main async task. Processes a loan application end-to-end.
    IDEMPOTENT: If application is already terminal or processing, returns stored state.
    """
    try:
        timeout_seconds = int(os.getenv("TASK_TIMEOUT_SECONDS", "60"))
        return asyncio.run(asyncio.wait_for(_process_application(application_id), timeout=timeout_seconds))
    except TimeoutError as exc:
        logger.exception(
            "process_application_timeout",
            application_id=application_id,
            step="PROCESS_APPLICATION",
            error=str(exc),
        )
        _mark_manual_review_after_system_error(application_id, exc, error_type="PIPELINE_TIMEOUT")
        return {
            "application_id": application_id,
            "status": "MANUAL_REVIEW",
            "decision": Decision.NEEDS_REVIEW.value,
            "error_type": "PIPELINE_TIMEOUT",
        }
    except Exception as exc:
        logger.exception(
            "process_application_unhandled_error",
            application_id=application_id,
            step="PROCESS_APPLICATION",
            error=str(exc),
        )
        _mark_manual_review_after_system_error(application_id, exc, error_type="SYSTEM_ERROR")
        return {
            "application_id": application_id,
            "status": "MANUAL_REVIEW",
            "decision": Decision.NEEDS_REVIEW.value,
            "error_type": "SYSTEM_ERROR",
        }


async def _process_application(application_id: str) -> dict[str, Any]:
    application = _claim_application(application_id)
    if application["terminal_or_locked"]:
        return application["response"]

    app_id = application["id"]
    user_data = application["user_data"]
    decision_user_data = _decision_user_data(user_data, application.get("pan_hash"))
    failure_flags = application["failure_flags"] or {}

    redis_client = redis_async.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
    try:
        credit_result, bank_result, gst_result = await _fetch_external_data(
            app_id,
            user_data,
            failure_flags,
            redis_client,
        )
    finally:
        await redis_client.aclose()

    decision_output = compute_decision_from_env(
        credit_result,
        bank_result,
        gst_result,
        decision_user_data,
    )

    _store_processing_results(
        app_id,
        user_data,
        failure_flags,
        credit_result,
        bank_result,
        gst_result,
        decision_output,
    )

    return {
        "application_id": str(app_id),
        "status": _status_for_decision(decision_output),
        "decision": decision_output.decision.value,
        "confidence": decision_output.confidence,
        "data_reliability": decision_output.data_reliability,
        "risk_score": decision_output.risk_score,
        "rule_version": decision_output.rule_version,
    }


def _claim_application(application_id: str) -> dict[str, Any]:
    app_uuid = UUID(application_id)
    with get_sync_session() as session:
        stale_before = datetime.now(UTC) - timedelta(seconds=_processing_lock_timeout_seconds())
        claim_statement = (
            update(LoanApplication)
            .where(LoanApplication.id == app_uuid)
            .where(
                or_(
                    LoanApplication.status == "PENDING",
                    and_(
                        LoanApplication.status == "PROCESSING",
                        LoanApplication.updated_at < stale_before,
                    ),
                )
            )
            .values(status="PROCESSING", updated_at=datetime.now(UTC))
            .returning(LoanApplication.id)
        )
        claimed_id = session.execute(claim_statement).scalar_one_or_none()

        application = session.execute(
            select(LoanApplication).where(LoanApplication.id == app_uuid)
        ).scalar_one()

        if claimed_id is None:
            if application.status in {"COMPLETED", "MANUAL_REVIEW"}:
                logger.info(
                    "application_already_claimed_or_processed",
                    application_id=application_id,
                    step="IDEMPOTENCY_GATE",
                    status=application.status,
                )
                return {
                    "terminal_or_locked": True,
                    "response": {
                        "application_id": str(application.id),
                        "status": application.status,
                        "decision": application.decision,
                        "confidence": float(application.confidence) if application.confidence is not None else None,
                    },
                }

            logger.info(
                "application_claimed_by_another_worker",
                application_id=application_id,
                step="IDEMPOTENCY_GATE",
                status=application.status,
            )
            return {
                "terminal_or_locked": True,
                "response": {
                    "application_id": str(application.id),
                    "status": application.status,
                    "message": "Being processed by another worker",
                },
            }

        write_audit_entry(
            application_id=application.id,
            step="PROCESSING_STARTED",
            input_snapshot={"status": application.status},
            output_snapshot={"status": "PROCESSING"},
            session=session,
        )

        return {
            "terminal_or_locked": False,
            "id": application.id,
            "user_data": _load_application_user_data(application),
            "pan_hash": application.pan_hash,
            "failure_flags": dict(application.failure_flags or {}),
        }


async def _fetch_external_data(
    application_id: UUID,
    user_data: dict[str, Any],
    failure_flags: dict[str, Any],
    redis_client: Any,
) -> tuple[ServiceResult, ServiceResult, ServiceResult]:
    pan = user_data["pan"]
    credit_service = CreditBureauService(redis_client=redis_client)
    bank_service = BankAnalyzerService(redis_client=redis_client)
    gst_service = GstVerifierService(redis_client=redis_client)

    return await asyncio.gather(
        _fetch_or_reuse_external_data(
            application_id,
            "CREDIT_BUREAU",
            "credit_bureau",
            failure_flags,
            lambda: credit_service.fetch(
                pan,
                application_id=str(application_id),
                fail_mode=_failure_flag(failure_flags, "credit_bureau"),
            ),
        ),
        _fetch_or_reuse_external_data(
            application_id,
            "BANK_ANALYZER",
            "bank_analyzer",
            failure_flags,
            lambda: bank_service.analyze(
                pan,
                bank_statement=user_data.get("bank_statement", []),
                application_id=str(application_id),
                fail_mode=_failure_flag(failure_flags, "bank_analyzer"),
            ),
        ),
        _fetch_or_reuse_external_data(
            application_id,
            "GST_VERIFIER",
            "gst_verifier",
            failure_flags,
            lambda: gst_service.verify(
                pan,
                application_id=str(application_id),
                fail_mode=_failure_flag(failure_flags, "gst_verifier"),
            ),
        ),
    )


async def _fetch_or_reuse_external_data(
    application_id: UUID,
    source_type: str,
    flag_key: str,
    failure_flags: dict[str, Any],
    fetch_call: Callable[[], Awaitable[ServiceResult]],
) -> ServiceResult:
    existing = _load_external_result(application_id, source_type)
    if existing is not None:
        logger.info(
            "external_data_reused",
            application_id=str(application_id),
            step=f"{source_type}_FETCH",
            source_type=source_type,
        )
        return existing

    result = await fetch_call()
    with get_sync_session() as session:
        existing_row = session.execute(
            select(ExternalData).where(
                ExternalData.application_id == application_id,
                ExternalData.source_type == source_type,
            )
        ).scalar_one_or_none()
        if existing_row is not None:
            return _service_result_from_external_data(existing_row)
        _store_external_result(session, application_id, source_type, flag_key, failure_flags, result)
    return result


def _load_external_result(application_id: UUID, source_type: str) -> ServiceResult | None:
    with get_sync_session() as session:
        row = session.execute(
            select(ExternalData).where(
                ExternalData.application_id == application_id,
                ExternalData.source_type == source_type,
            )
        ).scalar_one_or_none()
        return _service_result_from_external_data(row) if row is not None else None


def _store_processing_results(
    application_id: UUID,
    audit_user_data: dict[str, Any],
    failure_flags: dict[str, Any],
    credit_result: ServiceResult,
    bank_result: ServiceResult,
    gst_result: ServiceResult,
    decision_output: DecisionOutput,
) -> None:
    with get_sync_session() as session:
        application = session.execute(
            select(LoanApplication)
            .where(LoanApplication.id == application_id)
            .with_for_update()
        ).scalar_one()

        if application.status in {"COMPLETED", "MANUAL_REVIEW"}:
            logger.info(
                "application_already_processed",
                application_id=str(application_id),
                step="IDEMPOTENCY_GATE",
                status=application.status,
            )
            return

        status = _status_for_decision(decision_output)
        application.status = status
        application.decision = decision_output.decision.value
        application.confidence = Decimal(str(decision_output.confidence))
        loan_applications_total.labels(status=status).inc()
        decision_confidence.observe(decision_output.confidence)

        write_audit_entry(
            application_id=application_id,
            step="DECISION_CALCULATION",
            input_snapshot={
                "features": audit_safe_features(
                    audit_user_data,
                    _risk_score_audit_breakdown(audit_user_data, decision_output, credit_result, bank_result, gst_result),
                ),
                "failure_flags": failure_flags,
            },
            output_snapshot=decision_output.to_dict(),
            rule_version=decision_output.rule_version,
            session=session,
        )

        if decision_output.decision == Decision.NEEDS_REVIEW:
            write_audit_entry(
                application_id=application_id,
                step="MANUAL_REVIEW_OVERRIDE" if decision_output.requires_manual_review else "MANUAL_REVIEW_ROUTING",
                input_snapshot={"confidence": decision_output.confidence},
                output_snapshot={"decision": Decision.NEEDS_REVIEW.value, "status": status},
                fallback_used=decision_output.requires_manual_review,
                fallback_reason="Confidence below threshold" if decision_output.requires_manual_review else None,
                rule_version=decision_output.rule_version,
                session=session,
            )


def _store_external_result(
    session: Any,
    application_id: UUID,
    source_type: str,
    flag_key: str,
    failure_flags: dict[str, Any],
    result: ServiceResult,
) -> None:
    failure_type = result.failure_type.value if result.failure_type is not None else None
    session.add(
        ExternalData(
            application_id=application_id,
            source_type=source_type,
            request_params={"fail_mode": failure_flags.get(flag_key, "SUCCESS")},
            response_data=_redact_user_data(result.raw_response or result.data),
            failure_type=failure_type,
            idempotency_key=f"{source_type.lower()}:{application_id}",
        )
    )
    write_audit_entry(
        application_id=application_id,
        step=f"{source_type}_FETCH",
        input_snapshot={"fail_mode": failure_flags.get(flag_key, "SUCCESS")},
        output_snapshot={
            "success": result.success,
            "data": _redact_user_data(result.data),
            "raw_response": _redact_user_data(result.raw_response),
            "retry_count": result.retry_count,
            "latency_ms": result.latency_ms,
            "request_id": result.request_id,
        },
        error_type=failure_type,
        fallback_used=result.fallback_used,
        fallback_reason=failure_type,
        session=session,
    )


def _service_result_from_external_data(row: ExternalData) -> ServiceResult:
    failure_type = FailureType(row.failure_type) if row.failure_type else None
    response_data = dict(row.response_data or {})
    return ServiceResult(
        success=failure_type is None,
        data=response_data or None,
        raw_response=response_data or None,
        failure_type=failure_type,
        fallback_used=_fallback_used_for_reconstructed_result(failure_type),
        request_id=response_data.get("request_id"),
    )


def _fallback_used_for_reconstructed_result(failure_type: FailureType | None) -> bool:
    return failure_type in {
        FailureType.TIMEOUT,
        FailureType.SERVICE_DOWN,
        FailureType.FORMAT_ERROR,
        FailureType.PAN_MISMATCH,
        FailureType.NO_RECORD,
    }


def _mark_manual_review_after_system_error(application_id: str, exc: Exception, error_type: str) -> None:
    with get_sync_session() as session:
        application = session.get(LoanApplication, UUID(application_id))
        if application is None:
            return
        application.status = "MANUAL_REVIEW"
        application.decision = Decision.NEEDS_REVIEW.value
        loan_applications_total.labels(status="MANUAL_REVIEW").inc()
        write_audit_entry(
            application_id=application.id,
            step=error_type,
            input_snapshot={"application_id": application_id},
            output_snapshot={"status": "MANUAL_REVIEW", "decision": Decision.NEEDS_REVIEW.value},
            error_type=error_type,
            fallback_used=True,
            fallback_reason=str(exc),
            rule_version=os.getenv("RULE_SET_VERSION", "RULE_SET_V1"),
            session=session,
        )


def _status_for_decision(decision_output: DecisionOutput) -> str:
    if decision_output.decision == Decision.NEEDS_REVIEW:
        return "MANUAL_REVIEW"
    return "COMPLETED"


def _failure_flag(failure_flags: dict[str, Any], key: str) -> FailureType | None:
    value = failure_flags.get(key)
    if value is None:
        return None
    return value if isinstance(value, FailureType) else FailureType(value)


def _redact_user_data(user_data: dict[str, Any]) -> dict[str, Any]:
    if user_data is None:
        return {}
    redacted: dict[str, Any] = {}
    for key, value in user_data.items():
        if key in {"pan", "name", "pan_hash"}:
            redacted[key] = "***REDACTED***"
        elif key in {"monthly_income", "monthly_inflow"}:
            redacted[key] = "***REDACTED***"
        elif key == "existing_emis":
            redacted[key] = "***REDACTED***"
        elif key in {"loan_amount", "monthly_outflow", "average_balance", "annual_turnover"}:
            redacted[key] = "***REDACTED***"
        elif key == "bank_statement":
            redacted[key] = "***REDACTED***"
        elif isinstance(value, dict):
            redacted[key] = _redact_user_data(value)
        elif isinstance(value, list):
            redacted[key] = [_redact_user_data(item) if isinstance(item, dict) else item for item in value]
        else:
            redacted[key] = value
    return redacted


def _load_application_user_data(application: LoanApplication) -> dict[str, Any]:
    if application.encrypted_user_data is None or application.encryption_nonce is None:
        raise RuntimeError("Application is missing encrypted user data")
    return pii_service_from_env().decrypt(
        bytes(application.encrypted_user_data),
        bytes(application.encryption_nonce),
    )


def _decision_user_data(user_data: dict[str, Any], pan_hash: str | None) -> dict[str, Any]:
    safe_user_data = {
        "monthly_income": user_data["monthly_income"],
        "existing_emis": user_data.get("existing_emis", 0),
    }
    if pan_hash is not None:
        safe_user_data["pan_hash"] = pan_hash
    return safe_user_data


def _processing_lock_timeout_seconds() -> int:
    return int(os.getenv("PROCESSING_LOCK_TIMEOUT_SECONDS", "300"))


def _risk_score_audit_breakdown(
    user_data: dict[str, Any],
    decision_output: DecisionOutput,
    credit_result: ServiceResult,
    bank_result: ServiceResult,
    gst_result: ServiceResult,
) -> dict[str, Any]:
    monthly_income = float(user_data.get("monthly_income") or 0)
    existing_emis = float(user_data.get("existing_emis") or 0)
    dti = round(existing_emis / monthly_income, 4) if monthly_income > 0 else None
    failure_types = [
        result.failure_type.value
        for result in (credit_result, bank_result, gst_result)
        if result.failure_type is not None
    ]
    return {
        "dti": dti,
        "components": {
            "risk_score": decision_output.risk_score,
            "confidence": decision_output.confidence,
            "data_reliability": decision_output.data_reliability,
        },
        "failure_types": failure_types,
    }

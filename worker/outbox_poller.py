import os
import threading
import time
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from db.session import get_sync_session
from models.outbox import OutboxMessage


logger = structlog.get_logger()
_poller_started = False


def poll_outbox_once(limit: int = 10) -> int:
    from worker.celery_app import celery_app

    delivered = 0
    with get_sync_session() as session:
        messages = list(
            session.scalars(
                select(OutboxMessage)
                .where(OutboxMessage.status.in_(["PENDING", "FAILED"]))
                .order_by(OutboxMessage.created_at.asc(), OutboxMessage.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for message in messages:
            try:
                celery_app.send_task(
                    message.task_name,
                    args=[message.task_args["application_id"]],
                    task_id=f'{message.task_name}:{message.task_args["application_id"]}',
                )
                message.status = "PROCESSED"
                message.processed_at = datetime.now(UTC)
                message.error_message = None
                delivered += 1
            except Exception as exc:
                message.status = "FAILED"
                message.error_message = str(exc)
                logger.warning("outbox_delivery_failed", outbox_id=message.id, error=str(exc), step="OUTBOX")
    return delivered


def poll_outbox(poll_interval_seconds: float | None = None) -> None:
    interval = poll_interval_seconds or float(os.getenv("OUTBOX_POLL_INTERVAL_SECONDS", "1.0"))
    while True:
        poll_outbox_once()
        time.sleep(interval)


def start_outbox_poller() -> None:
    global _poller_started
    if _poller_started:
        return
    _poller_started = True
    thread = threading.Thread(target=poll_outbox, name="auditlend-outbox-poller", daemon=True)
    thread.start()

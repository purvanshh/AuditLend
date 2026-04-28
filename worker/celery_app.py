import os

from celery import Celery
from celery.signals import worker_ready
import structlog


structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
)


celery_app = Celery(
    "auditlend",
    broker=os.getenv("REDIS_URL", "redis://redis:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://redis:6379/0"),
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
)


@worker_ready.connect
def _start_outbox_poller_on_worker_ready(**_: object) -> None:
    from worker.outbox_poller import start_outbox_poller

    start_outbox_poller()

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from celery import Celery
from celery.signals import worker_ready
import structlog

from services.logging import setup_logging


setup_logging()
logger = structlog.get_logger()
_health_server_started = False

celery_app = Celery(
    "auditlend",
    broker=os.getenv("REDIS_URL", "redis://redis:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://redis:6379/0"),
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    imports=("worker.tasks.process_application",),
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
)


@worker_ready.connect
def _start_outbox_poller_on_worker_ready(**_: object) -> None:
    from worker.outbox_poller import start_outbox_poller

    start_health_server()
    start_outbox_poller()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"healthy","service":"auditlend-worker"}')
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def start_health_server(port: int | None = None) -> None:
    global _health_server_started
    if _health_server_started:
        return
    _health_server_started = True
    health_port = port or int(os.getenv("WORKER_HEALTH_PORT", "8004"))
    server = HTTPServer(("0.0.0.0", health_port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, name="auditlend-worker-health", daemon=True)
    thread.start()
    logger.info("worker_health_server_started", step="WORKER_HEALTH", port=health_port)

import os
from typing import Any

import structlog


def setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _add_message_field,
            structlog.processors.JSONRenderer(),
        ],
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None, **context: Any):
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    if context:
        return logger.bind(**context)
    return logger


def _add_message_field(logger, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event = event_dict.get("event")
    if event is not None and "message" not in event_dict:
        event_dict["message"] = str(event)
    if "application_id" not in event_dict:
        event_dict["application_id"] = None
    return event_dict


def log_level() -> str:
    return os.getenv("LOG_LEVEL", "INFO").upper()

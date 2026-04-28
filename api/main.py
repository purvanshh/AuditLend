import time
import uuid
from collections.abc import Callable

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routes import applications, decisions, explanations


structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger()


app = FastAPI(title="AuditLend API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(applications.router, prefix="/api/v1", tags=["applications"])
app.include_router(decisions.router, prefix="/api/v1", tags=["decisions"])
app.include_router(explanations.router, prefix="/api/v1", tags=["explanations"])

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Callable) -> Response:
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    started_at = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "http_request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=latency_ms,
        step="HTTP_REQUEST",
    )
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return _problem_response(
        request,
        status_code=exc.status_code,
        error_type=f"https://api.auditlend.local/errors/{exc.status_code}",
        title=_title_for_status(exc.status_code),
        detail=detail,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _problem_response(
        request,
        status_code=400,
        error_type="https://api.auditlend.local/errors/validation",
        title="Validation Error",
        detail=str(exc.errors()),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "auditlend-api", "version": "2.0.0"}


def _problem_response(
    request: Request,
    status_code: int,
    error_type: str,
    title: str,
    detail: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "type": error_type,
            "title": title,
            "detail": detail,
            "instance": str(request.url.path),
        },
        media_type="application/problem+json",
    )


def _title_for_status(status_code: int) -> str:
    if status_code == 404:
        return "Not Found"
    if status_code == 409:
        return "Conflict"
    if status_code == 202:
        return "Accepted"
    return "Request Error"

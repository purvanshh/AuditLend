from prometheus_client import Counter, Gauge, Histogram


loan_applications_total = Counter(
    "auditlend_applications_total",
    "Total loan applications",
    ["status"],
)

external_api_requests = Counter(
    "auditlend_external_api_requests_total",
    "External API calls",
    ["service", "status"],
)

external_api_latency = Histogram(
    "auditlend_external_api_latency_seconds",
    "External API call latency",
    ["service"],
)

circuit_breaker_state = Gauge(
    "auditlend_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half-open)",
    ["service"],
)

decision_confidence = Histogram(
    "auditlend_decision_confidence",
    "Decision confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

task_duration = Histogram(
    "auditlend_task_duration_seconds",
    "Celery task duration",
    ["task_name"],
)

task_failures = Counter(
    "auditlend_task_failures_total",
    "Celery task failures",
    ["task_name", "error_type"],
)


def circuit_state_value(state: str) -> int:
    return {
        "CLOSED": 0,
        "OPEN": 1,
        "HALF_OPEN": 2,
    }.get(state, 0)

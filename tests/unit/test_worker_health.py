from io import BytesIO

from worker.celery_app import HealthHandler


def test_worker_health_handler_responds() -> None:
    handler = object.__new__(HealthHandler)
    handler.path = "/health"
    handler.wfile = BytesIO()
    status_codes: list[int] = []
    headers: list[tuple[str, str]] = []

    handler.send_response = lambda status: status_codes.append(status)
    handler.send_header = lambda key, value: headers.append((key, value))
    handler.end_headers = lambda: None

    handler.do_GET()

    assert status_codes == [200]
    assert ("Content-Type", "application/json") in headers
    assert "auditlend-worker" in handler.wfile.getvalue().decode("utf-8")

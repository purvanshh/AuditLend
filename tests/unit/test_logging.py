from services.logging import _add_message_field


def test_logging_processor_adds_message_and_application_id() -> None:
    event = _add_message_field(None, "info", {"event": "external_service_success"})

    assert event["message"] == "external_service_success"
    assert event["application_id"] is None

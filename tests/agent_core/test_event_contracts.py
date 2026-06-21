import pytest
from agent_core.contracts import (
    EventPayloadValidationError,
    event_payload_schema_for,
    validate_event_payload,
)
from agent_core.domain.events import EventType


def test_event_payload_schema_for_session_created_contains_title_requirement() -> None:
    schema = event_payload_schema_for(EventType.SESSION_CREATED)

    assert schema["type"] == "object"
    assert schema["required"] == ["title"]
    assert schema["additionalProperties"] is False


def test_validate_event_payload_accepts_tool_execution_completed_shape() -> None:
    payload = validate_event_payload(
        EventType.TOOL_EXECUTION_COMPLETED,
        {
            "attempt_number": 1,
            "tool_name": "tests.run",
            "status": "executed",
            "output": "ok",
            "metadata": {"exit_code": 0},
        },
    )

    assert payload == {
        "attempt_number": 1,
        "tool_name": "tests.run",
        "status": "executed",
        "output": "ok",
        "metadata": {"exit_code": 0},
    }


def test_validate_event_payload_rejects_unknown_fields() -> None:
    with pytest.raises(
        EventPayloadValidationError,
        match="invalid payload for session_created",
    ):
        validate_event_payload(
            EventType.SESSION_CREATED,
            {"title": "Boot", "unexpected": True},
        )


def test_event_payload_schema_for_unknown_event_type_fails() -> None:
    with pytest.raises(
        KeyError,
        match="no payload schema registered for plan_proposed",
    ):
        event_payload_schema_for(EventType.PLAN_PROPOSED)

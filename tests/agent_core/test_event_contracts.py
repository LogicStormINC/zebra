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
        "tool_call_id": None,
        "status": "executed",
        "output": "ok",
        "metadata": {"exit_code": 0},
    }


def test_validate_event_payload_accepts_memory_candidate_extracted_shape() -> None:
    payload = validate_event_payload(
        EventType.MEMORY_CANDIDATE_EXTRACTED,
        {
            "memory_id": "mem-1",
            "memory_type": "procedure",
            "status": "candidate",
            "visibility": "repo",
            "text": "Run `make check` from `.`.",
            "confidence": 0.9,
            "source_event_start": 7,
            "source_event_end": 7,
            "repo_id": "zebra-agent",
        },
    )

    assert payload["memory_type"] == "procedure"
    assert payload["repo_id"] == "zebra-agent"


def test_validate_event_payload_accepts_memory_review_recorded_shape() -> None:
    payload = validate_event_payload(
        EventType.MEMORY_REVIEW_RECORDED,
        {
            "memory_id": "mem-1",
            "memory_type": "procedure",
            "previous_status": "candidate",
            "status": "confirmed",
            "operator": "alice",
            "reason": "validated locally",
            "superseded_memory_ids": ["mem-0"],
            "duplicate_of_memory_id": "mem-2",
        },
    )

    assert payload["status"] == "confirmed"
    assert payload["operator"] == "alice"
    assert payload["superseded_memory_ids"] == ["mem-0"]
    assert payload["duplicate_of_memory_id"] == "mem-2"


def test_validate_event_payload_rejects_unknown_fields() -> None:
    with pytest.raises(
        EventPayloadValidationError,
        match="invalid payload for session_created",
    ):
        validate_event_payload(
            EventType.SESSION_CREATED,
            {"title": "Boot", "unexpected": True},
        )


def test_validate_plan_updated_payload_rejects_duplicate_step_ids() -> None:
    with pytest.raises(EventPayloadValidationError, match="invalid payload for plan_updated"):
        validate_event_payload(
            EventType.PLAN_UPDATED,
            {
                "steps": [
                    {"step_id": "same", "content": "First", "status": "pending"},
                    {"step_id": "same", "content": "Second", "status": "completed"},
                ]
            },
        )


def test_event_payload_schema_for_unknown_event_type_fails() -> None:
    with pytest.raises(
        KeyError,
        match="no payload schema registered for plan_approved",
    ):
        event_payload_schema_for(EventType.PLAN_APPROVED)

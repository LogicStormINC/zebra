from __future__ import annotations

import pytest
from ag_ui.core import CustomEvent, Event, EventType, RawEvent, RunStartedEvent
from ag_ui.encoder import EventEncoder
from fixtures import RUN_ID, THREAD_ID
from pydantic import TypeAdapter, ValidationError
from sse_decoder import decode_sse_json

EXPECTED_EVENT_TYPES_0_1_19 = (
    "TEXT_MESSAGE_START",
    "TEXT_MESSAGE_CONTENT",
    "TEXT_MESSAGE_END",
    "TEXT_MESSAGE_CHUNK",
    "THINKING_TEXT_MESSAGE_START",
    "THINKING_TEXT_MESSAGE_CONTENT",
    "THINKING_TEXT_MESSAGE_END",
    "TOOL_CALL_START",
    "TOOL_CALL_ARGS",
    "TOOL_CALL_END",
    "TOOL_CALL_CHUNK",
    "TOOL_CALL_RESULT",
    "THINKING_START",
    "THINKING_END",
    "STATE_SNAPSHOT",
    "STATE_DELTA",
    "MESSAGES_SNAPSHOT",
    "ACTIVITY_SNAPSHOT",
    "ACTIVITY_DELTA",
    "RAW",
    "CUSTOM",
    "RUN_STARTED",
    "RUN_FINISHED",
    "RUN_ERROR",
    "STEP_STARTED",
    "STEP_FINISHED",
    "REASONING_START",
    "REASONING_MESSAGE_START",
    "REASONING_MESSAGE_CONTENT",
    "REASONING_MESSAGE_END",
    "REASONING_MESSAGE_CHUNK",
    "REASONING_END",
    "REASONING_ENCRYPTED_VALUE",
)


def test_event_type_snapshot_matches_reviewed_sdk_version() -> None:
    assert tuple(item.value for item in EventType) == EXPECTED_EVENT_TYPES_0_1_19


def test_unknown_discriminator_is_rejected_instead_of_silently_retyped() -> None:
    with pytest.raises(ValidationError) as captured:
        TypeAdapter(Event).validate_python({"type": "FUTURE_EVENT", "value": 1})

    assert captured.value.errors()[0]["type"] == "union_tag_invalid"


def test_custom_and_raw_events_are_explicit_forward_compatibility_exits() -> None:
    events = (
        CustomEvent(name="zebra.future", value={"revision": 2}),
        RawEvent(source="trench", event={"type": "HOST_NATIVE_EVENT", "revision": 2}),
    )
    wire = "".join(EventEncoder().encode(event) for event in events).encode()
    payloads = decode_sse_json([wire])

    validated = [TypeAdapter(Event).validate_python(payload) for payload in payloads]
    assert [event.type for event in validated] == [EventType.CUSTOM, EventType.RAW]
    assert payloads[0]["name"] == "zebra.future"
    assert payloads[1]["source"] == "trench"


def test_known_event_preserves_extension_fields_but_requires_core_identifiers() -> None:
    event = RunStartedEvent(
        thread_id=THREAD_ID,
        run_id=RUN_ID,
        extensionField={"revision": 2},
    )
    payload = decode_sse_json([EventEncoder().encode(event).encode()])[0]
    validated = TypeAdapter(Event).validate_python(payload)

    assert payload["extensionField"] == {"revision": 2}
    assert validated.model_dump(mode="json", by_alias=True)["extensionField"] == {"revision": 2}

    with pytest.raises(ValidationError, match="Field required"):
        TypeAdapter(Event).validate_python({"type": "RUN_STARTED", "runId": RUN_ID})

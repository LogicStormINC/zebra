from __future__ import annotations

import pytest
from ag_ui.core import Event, EventType
from ag_ui.encoder import EventEncoder
from fixtures import MESSAGE_ID, RUN_ID, THREAD_ID, TOOL_CALL_ID, canonical_events
from pydantic import TypeAdapter
from sse_decoder import SseDecodeError, decode_sse_json


def _encoded_stream() -> bytes:
    encoder = EventEncoder()
    return "".join(encoder.encode(event) for event in canonical_events()).encode()


def test_canonical_event_stream_round_trips_through_independent_sse_decoder() -> None:
    wire = _encoded_stream()
    chunks = [wire[index : index + 7] for index in range(0, len(wire), 7)]

    payloads = decode_sse_json(chunks)
    validated = [TypeAdapter(Event).validate_python(payload) for payload in payloads]

    assert EventEncoder().get_content_type() == "text/event-stream"
    assert payloads == [
        event.model_dump(mode="json", by_alias=True, exclude_none=True) for event in validated
    ]
    assert [payload["type"] for payload in payloads] == [
        EventType.RUN_STARTED.value,
        EventType.TEXT_MESSAGE_START.value,
        EventType.TEXT_MESSAGE_CONTENT.value,
        EventType.TEXT_MESSAGE_END.value,
        EventType.TOOL_CALL_START.value,
        EventType.TOOL_CALL_ARGS.value,
        EventType.TOOL_CALL_END.value,
        EventType.TOOL_CALL_RESULT.value,
        EventType.STATE_SNAPSHOT.value,
        EventType.STATE_DELTA.value,
        EventType.MESSAGES_SNAPSHOT.value,
        EventType.RUN_FINISHED.value,
    ]


def test_round_trip_preserves_run_message_and_tool_identifiers() -> None:
    payloads = decode_sse_json([_encoded_stream()])

    assert payloads[0]["threadId"] == THREAD_ID
    assert payloads[0]["runId"] == RUN_ID
    assert {
        payload["messageId"]
        for payload in payloads
        if str(payload["type"]).startswith("TEXT_MESSAGE_")
    } == {MESSAGE_ID}
    assert {
        payload["toolCallId"]
        for payload in payloads
        if str(payload["type"]).startswith("TOOL_CALL_")
    } == {TOOL_CALL_ID}


def test_decoder_rejects_truncation_and_bounded_resource_overflow() -> None:
    wire = _encoded_stream()

    with pytest.raises(SseDecodeError, match="blank-line terminated"):
        decode_sse_json([wire.rstrip(b"\n")])
    with pytest.raises(SseDecodeError, match="max_stream_bytes"):
        decode_sse_json([wire], max_stream_bytes=len(wire) - 1)
    with pytest.raises(SseDecodeError, match="max_event_bytes"):
        decode_sse_json([wire], max_event_bytes=8)
    with pytest.raises(SseDecodeError, match="max_events"):
        decode_sse_json([wire], max_events=1)

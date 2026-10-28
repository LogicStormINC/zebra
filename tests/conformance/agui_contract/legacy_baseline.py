"""Actual pinned Python projector, encoder and v2 wire output; no storage/model IO."""

from datetime import UTC, datetime
from importlib.metadata import version
from uuid import UUID

from ag_ui.encoder import EventEncoder
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import EventId, SessionId
from agent_integrations.ag_ui import AgUiCursor, AgUiProjector, AgUiRunIdentity
from agent_integrations.ag_ui.checkpoint_plan import (
    AG_UI_CHECKPOINT_VERSION,
    AG_UI_COVERAGE_CHECKPOINT_VERSION,
)
from zebra_agent_api.stream_v2_cursor import StreamV2Cursor, StreamV2CursorCodec
from zebra_agent_api.stream_v2_wire import canonical_wire, parse_record

NOW = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
IDENTITY = AgUiRunIdentity(
    session_id=SessionId(UUID(int=1)), thread_id="task-contract", run_id="execution-contract"
)
# Public fixture signing key only; it has never been a runtime credential.
CODEC = StreamV2CursorCodec(b"G0-offline-fixture-key-00000000000")


def scenarios() -> dict[str, tuple[SessionEvent, ...]]:
    source = {
        "text_tool_plan": [
            (EventType.TASK_PREPARED, {"title": "Inspect", "user_input": "Inspect"}),
            (EventType.PLAN_UPDATED, {"steps": ["Read evidence"]}),
            (
                EventType.MODEL_RESPONSE_DELTA,
                {"model_call_id": "model-1", "content_delta": "Found evidence."},
            ),
            (
                EventType.MODEL_RESPONSE_RECEIVED,
                {
                    "model_call_id": "model-1",
                    "assistant_message": "Found evidence.",
                    "response_stage": "final",
                },
            ),
            (
                EventType.TOOL_CALL_PROPOSED,
                {
                    "tool_call_id": "tool-1",
                    "tool_name": "repo.read",
                    "arguments": {"path": "README.md"},
                },
            ),
            (
                EventType.TOOL_EXECUTION_COMPLETED,
                {"tool_call_id": "tool-1", "tool_name": "repo.read", "output": "README"},
            ),
            (EventType.SESSION_COMPLETED, {"summary": "done"}),
        ],
        "clarification": [
            (
                EventType.CLARIFICATION_REQUESTED,
                {
                    "clarification_id": "clarify-1",
                    "tool_call_id": "clarify-1",
                    "question": "Which scope?",
                    "choices": ["event", "topic"],
                    "assistant_message": "Choose scope.",
                    "conversation": [],
                },
            ),
        ],
        "failure": [(EventType.SESSION_FAILED, {"summary": "policy blocked"})],
        "cancellation": [(EventType.TURN_CANCELLED, {"turn_id": "turn-1", "reason": "cancelled"})],
    }
    return {
        name: tuple(
            SessionEvent(
                event_id=EventId(UUID(int=100 + index)),
                session_id=IDENTITY.session_id,
                sequence=index,
                event_type=kind,
                payload=payload,
                actor=EventActor.HARNESS,
                created_at=NOW,
            )
            for index, (kind, payload) in enumerate(entries)
        )
        for name, entries in source.items()
    }


def legacy_records(events: tuple[SessionEvent, ...]) -> list[tuple[AgUiCursor, str]]:
    result = []
    for source, frames in AgUiProjector().project_events(events, IDENTITY):
        for frame_index, frame in enumerate(frames):
            cursor = AgUiCursor(
                thread_id=IDENTITY.thread_id,
                run_id=IDENTITY.run_id,
                sequence=source.sequence,
                event_id=str(source.event_id),
                frame_index=frame_index,
            )
            result.append((cursor, f"id: {cursor.encode()}\n{EventEncoder().encode(frame)}"))
    return result


def baseline() -> dict:
    results = {}
    for name, events in scenarios().items():
        projector = AgUiProjector()
        records = legacy_records(events)
        replays = []
        for cursor, _ in records:
            replay = projector.project(events, IDENTITY, after=cursor.encode())
            replays.append(
                {
                    "after": cursor.encode(),
                    "events": [
                        event.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for event in replay.events
                    ],
                }
            )
        v2 = []
        for cursor, record in records:
            for chunk_index, wire in canonical_wire(record, parse_record(record)[1]):
                token = CODEC.encode(
                    StreamV2Cursor(
                        "g0-scope",
                        durable=cursor.encode(),
                        chunk_index=chunk_index,
                    )
                )
                v2.append({"cursor": token, "wire": wire, "chunk_index": chunk_index})
        projection = projector.project(events, IDENTITY)
        results[name] = {
            "durable": [event.model_dump(mode="json") for event in events],
            "sse": [record for _, record in records],
            "replays": replays,
            "v2": v2,
            "next_cursor": projection.next_cursor.encode(),
        }
    return {
        "python_protocol_package": version("ag-ui-protocol"),
        "checkpoint_versions": [AG_UI_CHECKPOINT_VERSION, AG_UI_COVERAGE_CHECKPOINT_VERSION],
        "scenarios": results,
    }

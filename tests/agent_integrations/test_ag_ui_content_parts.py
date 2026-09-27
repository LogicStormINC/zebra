from datetime import UTC, datetime

from ag_ui.core import CustomEvent
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_event_id, new_session_id
from agent_integrations.ag_ui import AgUiProjector, AgUiRunIdentity

NOW = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)


def _event(
    session_id: SessionId,
    sequence: int,
    event_type: EventType,
    payload: dict[str, object],
) -> SessionEvent:
    return SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        actor=EventActor.HARNESS,
        created_at=NOW,
    )


def test_published_media_and_chart_project_typed_content_parts() -> None:
    session_id = new_session_id()
    cases = (
        ("image/png", "result.png", "image"),
        ("video/mp4", "demo.mp4", "video"),
        ("application/json", "revenue.vl.json", "chart"),
        ("image/svg+xml", "unsafe.svg", "file"),
    )
    events: list[SessionEvent] = []
    for offset, (mime_type, file_name, _) in enumerate(cases):
        call_id = f"tool-{offset}"
        artifact_id = f"00000000-0000-4000-8000-{offset:012d}"
        events.extend(
            (
                _event(
                    session_id,
                    offset * 2,
                    EventType.TOOL_CALL_PROPOSED,
                    {
                        "attempt_number": 1,
                        "tool_name": "files.publish",
                        "tool_call_id": call_id,
                        "arguments": {},
                    },
                ),
                _event(
                    session_id,
                    offset * 2 + 1,
                    EventType.TOOL_EXECUTION_COMPLETED,
                    {
                        "attempt_number": 1,
                        "tool_name": "files.publish",
                        "tool_call_id": call_id,
                        "status": "executed",
                        "output": "ready",
                        "metadata": {
                            "artifact_uri": f"artifact://{artifact_id}",
                            "delivery": True,
                            "file_name": file_name,
                            "mime_type": mime_type,
                            "size_bytes": 12,
                        },
                    },
                ),
            )
        )

    projection = AgUiProjector().project(
        tuple(events),
        AgUiRunIdentity(session_id=session_id, thread_id="task-1", run_id="segment-1"),
    )
    parts = [
        event.value["part"]
        for event in projection.events
        if isinstance(event, CustomEvent) and event.name == "zebra.content_part"
    ]

    assert [part["type"] for part in parts] == [expected for _, _, expected in cases]
    assert parts[0]["alt"] == "result.png"
    assert parts[1]["title"] == "demo.mp4"
    assert parts[2]["specType"] == "vega-lite"
    assert parts[2]["specVersion"] == "6"

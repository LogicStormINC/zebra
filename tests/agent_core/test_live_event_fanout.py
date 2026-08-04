from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.live_event_fanout import (
    LiveEventCursor,
    LiveEventEnvelope,
)


def _event(session_id: SessionId) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "live"},
    )


def test_live_event_types_are_immutable_and_keep_namespace() -> None:
    session_id = SessionId(uuid4())
    envelope = LiveEventEnvelope("deployment-a", _event(session_id), LiveEventCursor("0-1"))

    assert envelope.deployment_namespace == "deployment-a"
    assert envelope.event.session_id == session_id
    with pytest.raises(AttributeError):
        envelope.cursor = LiveEventCursor("0-2")  # type: ignore[misc]


@pytest.mark.parametrize("namespace", ["", " deployment-a", "deployment-a ", "x" * 256])
def test_live_event_envelope_rejects_invalid_namespace(namespace: str) -> None:
    with pytest.raises(ValueError, match="deployment_namespace"):
        LiveEventEnvelope(namespace, _event(SessionId(uuid4())), LiveEventCursor("0-1"))


@pytest.mark.parametrize("cursor", ["", " 0-1", "0-1 ", "x" * 129])
def test_live_event_cursor_rejects_invalid_value(cursor: str) -> None:
    with pytest.raises(ValueError, match="cursor"):
        LiveEventCursor(cursor)


def test_live_event_cursor_can_bind_an_opaque_stream_reference() -> None:
    cursor = LiveEventCursor("0-1", stream_ref="provider-stream-a")

    assert cursor.stream_ref == "provider-stream-a"


def test_live_event_cursor_rejects_non_text_stream_reference() -> None:
    with pytest.raises(ValueError, match="stream_ref"):
        LiveEventCursor("0-1", stream_ref=123)  # type: ignore[arg-type]

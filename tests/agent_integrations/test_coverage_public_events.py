"""Strict admission hides intermediate content without changing durable cursors."""

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId, new_event_id
from agent_core.ports.agent_tasks import TaskEvent
from agent_integrations.ag_ui import AgUiProjector
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_integrations.coverage_public_events import strict_coverage_events

from tests.agent_core.test_coverage_contracts import NOW
from tests.agent_integrations.test_ag_ui_coverage_projection import stream


def event(kind, sequence, payload, session_id):
    return SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=kind,
        actor=EventActor.SYSTEM,
        created_at=NOW,
        payload=payload,
    )


@pytest.mark.parametrize("raw", [None, {}, "invalid", {"mode": "strict"}])
def test_strict_presence_before_manifest_hides_text_and_advances_cursor(raw):
    _, identity = stream()
    events = (
        event(EventType.TASK_PREPARED, 1, {"coverage_admission": raw}, identity.session_id),
        event(
            EventType.MODEL_RESPONSE_RECEIVED,
            2,
            {"assistant_message": "secret candidate"},
            identity.session_id,
        ),
        event(
            EventType.MODEL_RESPONSE_DELTA,
            3,
            {"content_delta": "secret delta"},
            identity.session_id,
        ),
    )
    full = AgUiProjector().project(events, identity)
    assert strict_coverage_events(events)
    assert len(full.events) == 1  # RUN_STARTED only; not a fake final answer.
    assert full.next_cursor.sequence == 3
    first = AgUiProjector().project(events[:1], identity)
    tail = AgUiProjector().project(events, identity, after=first.next_cursor)
    assert not tail.events and tail.next_cursor == full.next_cursor
    assert events[-1].payload == {"content_delta": "secret delta"}


@pytest.mark.parametrize(
    "kind",
    [
        EventType.TOOL_CALL_PROPOSED,
        EventType.TOOL_EXECUTION_COMPLETED,
        EventType.ANSWER_COMMITTED,
        EventType.COVERAGE_ARTIFACT_MATERIALIZED,
        EventType.CLIENT_EFFECT_SCHEDULED,
        EventType.SUBAGENT_COMPLETED,
    ],
)
def test_progress_never_releases_private_outputs(kind):
    events, identity = stream()
    private = event(
        kind, 5, {"content": "secret", "artifact_uri": "artifact://secret"}, identity.session_id
    )
    projection = AgUiProjector().project((*events, private), identity)
    serialized = "".join(item.model_dump_json() for item in projection.events)
    assert "secret" not in serialized
    assert projection.next_cursor.sequence == 5
    assert any(
        getattr(item, "name", None) == "zebra.coverage_progress" for item in projection.events
    )


@pytest.mark.parametrize(
    "kind",
    [
        EventType.TURN_FAILED,
        EventType.SESSION_FAILED,
        EventType.SESSION_SUSPENDED,
        EventType.TURN_CANCELLED,
    ],
)
def test_terminal_error_text_cannot_leak_evidence(kind):
    events, identity = stream()
    terminal = event(kind, 5, {"reason": "secret", "summary": "secret"}, identity.session_id)
    projected = AgUiProjector().project((*events, terminal), identity)
    serialized = "".join(item.model_dump_json() for item in projected.events)
    assert "secret" not in serialized and "coverage_execution_ended" in serialized


def test_task_strict_identity_applies_across_segment_projection():
    _, identity = stream()
    first = event(EventType.TASK_PREPARED, 1, {"coverage_admission": None}, identity.session_id)
    second = event(
        EventType.MODEL_RESPONSE_RECEIVED, 1, {"assistant_message": "secret"}, identity.session_id
    )
    from uuid import uuid4

    from agent_core.domain.identifiers import SessionId

    second = second.model_copy(update={"session_id": SessionId(uuid4())})
    task = TaskId(identity.session_id)
    identity = identity.model_copy(update={"thread_id": str(task)})
    indexed = tuple(
        TaskEvent(task, i, row.session_id, row.sequence, row)
        for i, row in enumerate((first, second))
    )
    projection = AgUiTaskProjector().project_task(indexed, identity)
    assert "secret" not in "".join(item.model_dump_json() for item in projection.events)
    assert projection.next_cursor.sequence == 1


def test_ordinary_text_is_unchanged():
    _, identity = stream()
    row = event(
        EventType.MODEL_RESPONSE_RECEIVED,
        1,
        {"assistant_message": "ordinary answer"},
        identity.session_id,
    )
    result = AgUiProjector().project((row,), identity)
    assert "ordinary answer" in "".join(item.model_dump_json() for item in result.events)

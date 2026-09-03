"""Direct coverage for the ADR-026 per-turn AG-UI run semantics."""

from datetime import UTC, datetime
from pathlib import Path

from ag_ui.core import (
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.turns import derive_turn_id
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.projection import AgUiProjector

NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)


def _stream():
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="AG-UI turn semantics",
            user_input="Turn one.",
            workspace_root=Path("/tmp/agui-turns"),
        )
    )
    events = list(bootstrap.events)

    def add(event_type, payload, actor=EventActor.HARNESS):
        events.append(
            SessionEvent.create(
                session_id=events[0].session_id,
                sequence=events[-1].sequence + 1,
                event_type=event_type,
                actor=actor,
                payload=payload,
                created_at=NOW,
            )
        )

    return events, add


def _identity(events):
    return AgUiRunIdentity(
        session_id=events[0].session_id, thread_id="task-1", run_id="segment-1"
    )


def test_per_turn_run_start_and_finish_boundaries() -> None:
    events, add = _stream()
    first = derive_turn_id(events[0].session_id, 0)
    second = derive_turn_id(events[0].session_id, 1)
    add(EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    add(
        EventType.MODEL_RESPONSE_DELTA,
        {
            "model_call_id": "m1",
            "content_delta": "hel",
            "attempt_number": 1,
            "delta_index": 0,
        },
    )
    add(
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "m1", "assistant_message": "hello"},
    )
    add(
        EventType.TURN_COMPLETED,
        {"turn_id": str(first), "turn_index": 0, "closes_segment": False},
    )
    add(
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "Turn two.", "turn_id": str(second), "turn_index": 1, "origin": "human"},
        actor=EventActor.USER,
    )
    add(EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    add(
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "m2", "assistant_message": "second"},
    )
    add(
        EventType.TURN_COMPLETED,
        {"turn_id": str(second), "turn_index": 1, "closes_segment": False},
    )

    projection = AgUiProjector().project(events, _identity(events))
    kinds = [type(event) for event in projection.events]

    assert kinds.count(RunStartedEvent) == 2  # segment start + second turn
    assert kinds.count(RunFinishedEvent) == 2  # one finish per completed turn
    # text messages still stream normally across both turns
    assert kinds.count(TextMessageStartEvent) == 2
    assert kinds.count(TextMessageEndEvent) == 2


def test_turn_cancelled_finishes_the_run_with_interrupt_outcome() -> None:
    events, add = _stream()
    first = derive_turn_id(events[0].session_id, 0)
    add(EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    add(
        EventType.TURN_CANCELLED,
        {"turn_id": str(first), "turn_index": 0, "reason": "session_cancelled"},
        actor=EventActor.SYSTEM,
    )
    add(EventType.SESSION_CANCELLED, {})

    projection = AgUiProjector().project(events, _identity(events))
    finishes = [
        event
        for event in projection.events
        if isinstance(event, RunFinishedEvent)
    ]

    assert len(finishes) == 1
    outcome = finishes[0].outcome
    assert outcome.type == "interrupt"
    assert outcome.interrupts[0].reason == "session_cancelled"


def test_handoff_workspace_drift_fails_the_run_instead_of_hanging() -> None:
    events, add = _stream()
    add(
        EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED,
        {
            "handoff_id": "handoff-1",
            "expected_revision_hash": "expected",
            "actual_revision_hash": "actual",
        },
        actor=EventActor.SYSTEM,
    )

    projection = AgUiProjector().project(events, _identity(events))
    errors = [event for event in projection.events if isinstance(event, RunErrorEvent)]

    assert len(errors) == 1
    assert errors[0].code == "zebra_handoff_workspace_drift"
    assert "Retry the request" in errors[0].message


def test_mid_stream_cursor_replay_keeps_turn_boundaries_stable() -> None:
    events, add = _stream()
    first = derive_turn_id(events[0].session_id, 0)
    second = derive_turn_id(events[0].session_id, 1)
    add(EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    add(
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "m1", "assistant_message": "one"},
    )
    add(
        EventType.TURN_COMPLETED,
        {"turn_id": str(first), "turn_index": 0, "closes_segment": False},
    )
    boundary = AgUiProjector().project(events, _identity(events)).next_cursor

    add(
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "Turn two.", "turn_id": str(second), "turn_index": 1, "origin": "human"},
        actor=EventActor.USER,
    )
    add(EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    add(
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "m2", "assistant_message": "two"},
    )
    add(
        EventType.TURN_COMPLETED,
        {"turn_id": str(second), "turn_index": 1, "closes_segment": False},
    )

    tail = AgUiProjector().project(events, _identity(events), after=boundary)
    kinds = [type(event) for event in tail.events]
    # the reconnect tail starts the second run and finishes it
    assert kinds[0] is RunStartedEvent
    assert kinds[-1] is RunFinishedEvent

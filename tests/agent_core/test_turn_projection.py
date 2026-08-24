from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import (
    SessionBootstrapCommand,
    SessionBootstrapService,
    interaction_mode_of,
    is_human_message,
    project_turns,
)
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.turns import InteractionMode, TurnStatus, derive_turn_id

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _bootstrap(*, interaction_mode: str | None = None) -> list[SessionEvent]:
    command = SessionBootstrapCommand(
        title="Turn lifecycle",
        user_input="First turn input.",
        workspace_root=Path("/tmp/turns"),
        created_at=NOW,
    )
    if interaction_mode is not None:
        command = type(command)(
            title=command.title,
            user_input=command.user_input,
            workspace_root=command.workspace_root,
            created_at=NOW,
            interaction_mode=InteractionMode(interaction_mode),
        )
    return list(SessionBootstrapService().build(command).events)


def _event(
    events: list[SessionEvent],
    event_type: EventType,
    payload: dict[str, object],
    *,
    actor: EventActor = EventActor.HARNESS,
) -> SessionEvent:
    return SessionEvent.create(
        session_id=events[0].session_id,
        sequence=events[-1].sequence + 1,
        event_type=event_type,
        actor=actor,
        payload=payload,
        created_at=NOW,
    )


def test_conversation_turns_keep_one_segment_alive() -> None:
    events = _bootstrap(interaction_mode="conversation")
    first_turn = derive_turn_id(events[0].session_id, 0)
    second_turn = derive_turn_id(events[0].session_id, 1)
    events.append(_event(events, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}))
    events.append(
        _event(
            events,
            EventType.TURN_COMPLETED,
            {
                "turn_id": str(first_turn),
                "turn_index": 0,
                "summary": "done",
                "closes_segment": False,
            },
        )
    )

    session = rebuild_session(events)
    assert session.status is SessionStatus.AWAITING_TURN

    # The next human message re-arms the segment for the worker queue.
    events.append(
        _event(
            events,
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "Second turn.",
                "turn_id": str(second_turn),
                "turn_index": 1,
                "origin": "human",
            },
            actor=EventActor.USER,
        )
    )
    assert rebuild_session(events).status is SessionStatus.READY

    records = project_turns(events)
    assert [record.status for record in records] == [TurnStatus.COMPLETED, TurnStatus.RUNNING]
    assert records[0].turn_id == str(first_turn)
    assert records[0].closes_segment is False
    assert interaction_mode_of(events) is InteractionMode.CONVERSATION


def test_one_shot_turn_close_is_followed_by_session_terminal() -> None:
    events = _bootstrap()  # legacy admission without interaction_mode
    first_turn = derive_turn_id(events[0].session_id, 0)
    events.append(_event(events, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}))
    events.append(
        _event(
            events,
            EventType.TURN_COMPLETED,
            {"turn_id": str(first_turn), "turn_index": 0, "closes_segment": True},
        )
    )
    assert rebuild_session(events).status is SessionStatus.RUNNING

    events.append(
        _event(events, EventType.SESSION_COMPLETED, {"attempt_number": 1, "summary": "done"})
    )
    session = rebuild_session(events)
    assert session.status is SessionStatus.COMPLETED

    records = project_turns(events)
    assert len(records) == 1
    assert records[0].status is TurnStatus.COMPLETED
    assert records[0].closes_segment is True
    assert records[0].legacy is False
    assert interaction_mode_of(events) is InteractionMode.ONE_SHOT


def _legacy_event(
    session_id: object,
    sequence: int,
    event_type: EventType,
    payload: dict[str, object],
    *,
    actor: EventActor = EventActor.HARNESS,
) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id,  # type: ignore[arg-type]
        sequence=sequence,
        event_type=event_type,
        actor=actor,
        payload=payload,
        created_at=NOW,
    )


def test_legacy_stream_without_turn_events_replays_as_one_shot() -> None:
    session_id = _bootstrap()[0].session_id
    events = [
        _legacy_event(
            session_id, 0, EventType.SESSION_CREATED, {"title": "legacy"}, actor=EventActor.USER
        ),
        _legacy_event(
            session_id,
            1,
            EventType.USER_MESSAGE_RECEIVED,
            {"content": "legacy input"},
            actor=EventActor.USER,
        ),
        _legacy_event(
            session_id,
            2,
            EventType.TASK_PREPARED,
            {"title": "legacy", "user_input": "legacy input"},
        ),
        _legacy_event(
            session_id, 3, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}
        ),
        _legacy_event(
            session_id,
            4,
            EventType.SESSION_COMPLETED,
            {"attempt_number": 1, "summary": "done"},
        ),
    ]

    records = project_turns(events)
    assert len(records) == 1
    assert records[0].legacy is True
    assert records[0].status is TurnStatus.COMPLETED
    assert records[0].turn_id.startswith("legacy-turn:")
    assert interaction_mode_of(events) is InteractionMode.ONE_SHOT


def test_automation_seed_never_opens_a_turn() -> None:
    events = _bootstrap()
    events.append(
        _event(
            events,
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "Continue from the verified Task checkpoint.",
                "source": "session_handoff",
                "handoff_id": "00000000-0000-0000-0000-000000000bb2",
                "principal_identity_hash": "0f" * 32,
                "actor_kind": "automation",
                "trust": "automation",
            },
            actor=EventActor.USER,
        )
    )

    records = project_turns(events)
    assert len(records) == 1  # the bootstrap human message only
    assert records[0].legacy is False
    assert not is_human_message(events[-1])

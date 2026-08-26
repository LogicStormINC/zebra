from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.workspaces import WorkspaceStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from zebra_agent_worker import SessionControlService


def test_session_control_service_cancels_ready_session(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)

    result = SessionControlService(database_path).cancel_session(session_id)

    updated_session = SQLiteProjectionStore(database_path).get_session(session_id)
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)
    events = SQLiteEventStore(database_path).list_for_session(session_id)

    assert result.event.event_type is EventType.SESSION_CANCELLED
    assert updated_session is not None
    assert updated_session.status is SessionStatus.CANCELLED
    assert workspace is not None
    assert workspace.status is WorkspaceStatus.CANCELLED
    assert events[-1].event_type is EventType.SESSION_CANCELLED


def test_session_control_retries_when_live_execution_wins_sequence(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    service = SessionControlService(database_path)
    append = service._event_store.append
    raced = False

    def append_with_race(event: SessionEvent) -> SessionEvent:
        nonlocal raced
        if event.event_type is EventType.SESSION_CANCELLED and not raced:
            raced = True
            append(
                SessionEvent.create(
                    session_id=session_id,
                    sequence=event.sequence,
                    event_type=EventType.HARNESS_ATTEMPT_STARTED,
                    actor=EventActor.HARNESS,
                    payload={"attempt_number": 1},
                )
            )
        return append(event)

    monkeypatch.setattr(service._event_store, "append", append_with_race)

    result = service.cancel_session(session_id)

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert raced
    assert result.event.sequence == events[-2].sequence + 1
    assert events[-2].event_type is EventType.HARNESS_ATTEMPT_STARTED
    assert events[-1].event_type is EventType.SESSION_CANCELLED


def _seed_ready_session(database_path: Path, *, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Worker cancel",
            user_input="Inspect and continue.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        rebuild_workspace(list(bootstrap.events))
    )
    return bootstrap.session.session_id


def test_cancel_with_open_turn_writes_turn_cancelled_first(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_running_session_with_open_turn(database_path, workspace_root=tmp_path)

    result = SessionControlService(database_path).cancel_session(session_id)

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    updated_session = SQLiteProjectionStore(database_path).get_session(session_id)
    assert [event.event_type for event in events[-2:]] == [
        EventType.TURN_CANCELLED,
        EventType.SESSION_CANCELLED,
    ]
    turn_event = events[-2]
    assert turn_event.payload["turn_id"]
    assert turn_event.idempotency_key == f"turn-cancel:{turn_event.payload['turn_id']}"
    assert updated_session is not None
    assert updated_session.status is SessionStatus.CANCELLED
    assert result.event.event_type is EventType.SESSION_CANCELLED


def test_awaiting_turn_session_is_suspendable_and_cancellable(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_awaiting_turn_session(database_path, workspace_root=tmp_path)
    service = SessionControlService(database_path)

    suspended = service.suspend_session(session_id)
    assert suspended.event.event_type is EventType.SESSION_SUSPENDED

    restored_session = SQLiteProjectionStore(database_path).get_session(session_id)
    assert restored_session is not None
    assert restored_session.status is SessionStatus.SUSPENDED


def _seed_running_session_with_open_turn(
    database_path: Path, *, workspace_root: Path):

    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Running turn",
            user_input="Execute me",
            workspace_root=workspace_root,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    event_store.append(
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=bootstrap.session.current_sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
    )
    from agent_core.application.session_projection import rebuild_session

    session = rebuild_session(event_store.list_for_session(bootstrap.session.session_id))
    SQLiteProjectionStore(database_path).save_session(session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        rebuild_workspace(event_store.list_for_session(bootstrap.session.session_id))
    )
    return bootstrap.session.session_id


def _seed_awaiting_turn_session(
    database_path: Path, *, workspace_root: Path):
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.turns import derive_turn_id

    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Awaiting",
            user_input="One round",
            workspace_root=workspace_root,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    events = event_store.list_for_session(bootstrap.session.session_id)
    event_store.append(
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=events[-1].sequence + 2,
            event_type=EventType.TURN_COMPLETED,
            actor=EventActor.HARNESS,
            payload={
                "turn_id": str(derive_turn_id(bootstrap.session.session_id, 0)),
                "turn_index": 0,
                "closes_segment": False,
            },
        )
    )
    session = rebuild_session(event_store.list_for_session(bootstrap.session.session_id))
    SQLiteProjectionStore(database_path).save_session(session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        rebuild_workspace(event_store.list_for_session(bootstrap.session.session_id))
    )
    return bootstrap.session.session_id

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import sqlite_control_plane_stores
from zebra_agent_worker.command_consumer import SessionCommandConsumer


class _ExecutionSpy:
    def __init__(self, stores) -> None:
        self.stores = stores
        self.calls: list[tuple[SessionId, str, int]] = []

    def execute_session(self, session_id: SessionId, *, worker_id: str, lease_ttl_seconds: int):
        self.calls.append((session_id, worker_id, lease_ttl_seconds))
        session = self.stores.sessions.get_session(session_id)
        assert session is not None
        latest = self.stores.events.list_for_session(session_id)[-1]
        self.stores.sessions.save_session(
            session.model_copy(update={"current_sequence": latest.sequence})
        )


class _ControlSpy:
    def __init__(self) -> None:
        self.cancelled: list[SessionId] = []
        self.suspended: list[SessionId] = []

    def cancel_session(self, session_id: SessionId) -> None:
        self.cancelled.append(session_id)

    def suspend_session(self, session_id: SessionId) -> None:
        self.suspended.append(session_id)


def test_consumer_wakes_worker_and_does_not_replay_projected_command(tmp_path: Path) -> None:
    stores, session_id, revision = _seed_session(tmp_path)
    command = SessionCommand(
        command_id=uuid4(),
        session_id=session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=revision,
        idempotency_key="run-worker-1",
    )
    stores.events.append(_command_event(command, revision + 1))
    execution = _ExecutionSpy(stores)
    consumer = SessionCommandConsumer(stores, execution)  # type: ignore[arg-type]

    first = consumer.consume_once(worker_id="worker-a", lease_ttl_seconds=30)
    second = consumer.consume_once(worker_id="worker-a", lease_ttl_seconds=30)

    assert first.status == "executed"
    assert second.status == "idle"
    assert execution.calls == [(session_id, "worker-a", 30)]


def test_message_command_appends_user_event_before_waking_worker(tmp_path: Path) -> None:
    stores, session_id, revision = _seed_session(tmp_path)
    command = SessionCommand(
        command_id=uuid4(),
        session_id=session_id,
        kind=SessionCommandKind.MESSAGE,
        expected_revision=revision,
        idempotency_key="message-worker-1",
        payload={"content": "continue", "clarification_id": None},
    )
    stores.events.append(_command_event(command, revision + 1))
    execution = _ExecutionSpy(stores)

    result = SessionCommandConsumer(stores, execution).consume_once(
        worker_id="worker-b",
        lease_ttl_seconds=45,
    )  # type: ignore[arg-type]

    assert result.status == "executed"
    events = stores.events.list_for_session(session_id)
    assert [event.event_type for event in events[-2:]] == [
        EventType.SESSION_COMMAND_ACCEPTED,
        EventType.USER_MESSAGE_RECEIVED,
    ]
    assert events[-1].payload["content"] == "continue"


@pytest.mark.parametrize(
    ("kind", "control_attr"),
    (
        (SessionCommandKind.STOP, "cancelled"),
        (SessionCommandKind.CANCEL, "cancelled"),
        (SessionCommandKind.SUSPEND, "suspended"),
    ),
)
def test_control_command_is_applied_by_worker_without_execution(
    tmp_path: Path, kind: SessionCommandKind, control_attr: str
) -> None:
    stores, session_id, revision = _seed_session(tmp_path)
    command = SessionCommand(
        command_id=uuid4(),
        session_id=session_id,
        kind=kind,
        expected_revision=revision,
        idempotency_key=f"{kind.value}-worker-1",
    )
    stores.events.append(_command_event(command, revision + 1))
    execution = _ExecutionSpy(stores)
    control = _ControlSpy()
    consumer = SessionCommandConsumer(stores, execution, control_service=control)  # type: ignore[arg-type]

    result = consumer.consume_once(worker_id="worker-c", lease_ttl_seconds=30)

    assert result.status == "executed"
    assert execution.calls == []
    assert getattr(control, control_attr) == [session_id]


def _seed_session(tmp_path: Path):
    database_path = tmp_path / "worker.sqlite"
    stores = sqlite_control_plane_stores(database_path)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Command worker",
            user_input="Execute the command.",
            workspace_root=tmp_path.resolve(),
        )
    )
    for event in bootstrap.events:
        stores.events.append(event)
    stores.sessions.save_session(bootstrap.session)
    stores.workspaces.save_workspace(rebuild_workspace(list(bootstrap.events)))
    return stores, bootstrap.session.session_id, bootstrap.session.current_sequence


def _command_event(command: SessionCommand, sequence: int) -> SessionEvent:
    return SessionEvent.create(
        session_id=command.session_id,
        sequence=sequence,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=command.idempotency_key,
    )


def test_worker_loop_skips_poisoned_ready_sessions_without_crashing(tmp_path, monkeypatch):
    """One failing ready session must not kill the whole worker loop."""
    from zebra_agent_worker.execution_finalization import WorkerExecutionError
    from zebra_agent_worker.loop import WorkerLoopService

    class _PoisonedExecution:
        def __init__(self) -> None:
            self.calls = 0

        def execute_session(self, session_id, **_kwargs):
            self.calls += 1
            raise WorkerExecutionError("poisoned session")

    class _ReadyProjection:
        def list_ready_sessions(self, *, limit):
            from datetime import UTC, datetime

            from agent_core.domain.identifiers import new_session_id
            from agent_core.domain.sessions import Session as _Session

            return [
                _Session(
                    session_id=new_session_id(),
                    status="ready",
                    title="poisoned",
                    created_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
                    current_sequence=0,
                )
            ]

    execution = _PoisonedExecution()
    loop = WorkerLoopService(
        projection_store=_ReadyProjection(),
        execution_service=execution,
        sleep=lambda _: None,
        command_consumer=None,
    )
    result = loop.poll_once(worker_id="worker-a", batch_size=1, lease_ttl_seconds=30)
    assert execution.calls == 1
    assert len(result.skipped_session_ids) == 1
    assert result.executed_session_ids == ()

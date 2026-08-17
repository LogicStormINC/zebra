from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import (
    apply_event as apply_workspace_event,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.leases import LeaseFence, WorkerLease
from agent_core.domain.workspaces import WorkspaceStatus
from agent_core.ports import WorkerProjectionCommitResult
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from zebra_agent_worker import SessionRecoveryError, SessionRecoveryService


def test_session_recovery_service_rebuilds_and_persists_projection(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "worker.db"
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)
    workspace_store = SQLiteWorkspaceProjectionStore(database_path)
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 30, tzinfo=UTC)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Recover Session"},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": "Recover Session",
                "user_input": "continue",
                "workspace_root": str(tmp_path / "workspace"),
            },
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        )
    )

    recovered = SessionRecoveryService(
        event_store,
        projection_store,
        workspace_store,
    ).recover_session(session_id)

    assert recovered.event_count == 3
    assert recovered.last_sequence == 2
    assert recovered.is_terminal is False
    assert recovered.session.status.value == "running"
    assert recovered.workspace.workspace_root == str(tmp_path / "workspace")
    assert recovered.workspace.status is WorkspaceStatus.RUNNING
    assert projection_store.get_session(session_id) == recovered.session
    assert workspace_store.get_workspace(session_id) == recovered.workspace


def test_session_recovery_service_marks_terminal_session(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)
    workspace_store = SQLiteWorkspaceProjectionStore(database_path)
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 35, tzinfo=UTC)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Terminal Session"},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": "Terminal Session",
                "user_input": "continue",
                "workspace_root": str(tmp_path / "workspace-terminal"),
            },
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=created_at,
        )
    )

    recovered = SessionRecoveryService(
        event_store,
        projection_store,
        workspace_store,
    ).recover_session(session_id)

    assert recovered.is_terminal is True
    assert recovered.session.status.value == "completed"
    assert recovered.workspace.status is WorkspaceStatus.COMPLETED


def test_session_recovery_service_rejects_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)
    workspace_store = SQLiteWorkspaceProjectionStore(database_path)

    with pytest.raises(SessionRecoveryError, match="cannot recover missing session"):
        SessionRecoveryService(
            event_store,
            projection_store,
            workspace_store,
        ).recover_session(new_session_id())


def test_session_recovery_service_resumes_from_projection_delta(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)
    workspace_store = SQLiteWorkspaceProjectionStore(database_path)
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 40, tzinfo=UTC)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Resume Delta"},
            created_at=created_at,
        )
    )
    task_prepared = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={
            "title": "Resume Delta",
            "user_input": "continue",
            "workspace_root": str(tmp_path / "workspace-delta"),
        },
        created_at=created_at,
    )
    event_store.append(task_prepared)
    stale_projection = rebuild_session(event_store.list_for_session(session_id))
    projection_store.save_session(stale_projection)
    SessionRecoveryService(
        event_store,
        projection_store,
        workspace_store,
    ).recover_session(session_id)
    attempt_started = SessionEvent.create(
        session_id=session_id,
        sequence=2,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
        created_at=created_at,
    )
    event_store.append(attempt_started)
    completed = SessionEvent.create(
        session_id=session_id,
        sequence=3,
        event_type=EventType.SESSION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"summary": "done"},
        created_at=created_at,
    )
    event_store.append(completed)

    recovered = SessionRecoveryService(
        event_store,
        projection_store,
        workspace_store,
    ).recover_session(session_id)

    assert recovered.event_count == 4
    assert recovered.last_sequence == 3
    assert recovered.is_terminal is True
    assert recovered.session.status.value == "completed"
    assert projection_store.get_session(session_id) == recovered.session
    assert workspace_store.get_workspace(session_id) == recovered.workspace
    assert recovered.workspace.status is WorkspaceStatus.COMPLETED


def test_cloud_recovery_projects_persisted_effect_with_current_lease() -> None:
    created_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Fenced effect recovery",
            user_input="continue",
            workspace_root=Path("/tmp/fenced-effect-recovery"),
        )
    )
    workspace = rebuild_workspace(list(bootstrap.events))
    terminal = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=bootstrap.session.current_sequence + 1,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "command.run",
            "status": "succeeded",
            "output": "effect output",
            "metadata": {},
        },
        created_at=created_at,
    )
    projection_store = Mock()
    projection_store.get_session.return_value = bootstrap.session
    workspace_store = Mock()
    workspace_store.get_workspace.return_value = workspace
    event_store = Mock()
    event_store.list_for_session.return_value = [*bootstrap.events, terminal]
    transaction = Mock()
    expected_session = rebuild_session([*bootstrap.events, terminal])
    expected_workspace = apply_workspace_event(workspace, terminal)
    transaction.project_persisted_worker_event.return_value = WorkerProjectionCommitResult(
        event=terminal,
        session=expected_session,
        workspace=expected_workspace,
    )
    model_indexer = Mock()
    tool_indexer = Mock()
    lease = WorkerLease(
        session_id=bootstrap.session.session_id,
        fence=LeaseFence(
            control_plane_epoch=uuid4(),
            fencing_token=4,
            owner_instance_id="worker-recovery",
        ),
        checkpoint=bootstrap.session.current_sequence,
        acquired_at=created_at,
        heartbeat_at=created_at,
        expires_at=datetime(2026, 8, 12, 12, 1, tzinfo=UTC),
    )

    recovered = SessionRecoveryService(
        event_store,
        projection_store,
        workspace_store,
        worker_projection_transaction=transaction,
        deployment_namespace="cloud-effect-recovery",
        model_call_indexer=model_indexer,
        tool_run_indexer=tool_indexer,
    ).recover_session(bootstrap.session.session_id, worker_lease=lease)

    first_authority = model_indexer.index_worker_event.call_args_list[0].kwargs["authority"]
    terminal_authority = transaction.project_persisted_worker_event.call_args.kwargs["authority"]
    assert recovered.session == expected_session
    assert recovered.workspace == expected_workspace
    assert first_authority.expected_stream_revision == -1
    assert terminal_authority.expected_stream_revision == bootstrap.session.current_sequence
    transaction.project_persisted_worker_event.assert_called_once_with(
        terminal,
        expected_session,
        expected_workspace,
        authority=terminal_authority,
    )
    assert model_indexer.index_worker_event.call_count == len(event_store.list_for_session())
    assert tool_indexer.index_worker_event.call_count == len(event_store.list_for_session())
    projection_store.save_session.assert_not_called()
    workspace_store.save_workspace.assert_not_called()

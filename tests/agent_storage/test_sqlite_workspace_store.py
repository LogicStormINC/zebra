from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import (
    SQLiteWorkspaceProjectionStore,
    session_policy_profile_for_session,
)


def test_sqlite_workspace_projection_store_round_trips_workspace_projection(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkspaceProjectionStore(tmp_path / "workspace.db")
    created_at = datetime(2026, 6, 29, 18, 30, tzinfo=UTC)
    projection = WorkspaceProjection.model_validate(
        {
            "session_id": new_session_id(),
            "workspace_root": "/tmp/workspace-round-trip",
            "prepared_at": created_at,
            "updated_at": created_at,
            "current_sequence": 3,
            "status": WorkspaceStatus.RUNNING,
            "policy_profile": "workspace_write",
            "last_attempt_number": 1,
            "runtime_name": "local",
            "snapshot_id": "snap-001",
            "snapshot_path": "/tmp/snapshots/snap-001",
        }
    )

    store.save_workspace(projection)
    loaded = store.get_workspace(projection.session_id)

    assert loaded == projection


def test_sqlite_workspace_projection_store_persists_rebuilt_workspace_state(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkspaceProjectionStore(tmp_path / "workspace.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 29, 18, 45, tzinfo=UTC)
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "Workspace Store"},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": "Workspace Store",
                "user_input": "continue",
                "workspace_root": "/tmp/workspace-store",
                "policy_profile": "workspace_write",
            },
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 2},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=created_at,
        ),
    ]

    rebuilt = rebuild_workspace(events)
    store.save_workspace(rebuilt)
    loaded = store.get_workspace(session_id)

    assert loaded is not None
    assert loaded == rebuilt
    assert loaded.status is WorkspaceStatus.COMPLETED
    assert loaded.last_attempt_number == 2


def test_sqlite_workspace_projection_store_persists_snapshot_metadata(tmp_path: Path) -> None:
    store = SQLiteWorkspaceProjectionStore(tmp_path / "workspace.db")
    created_at = datetime(2026, 6, 29, 18, 50, tzinfo=UTC)
    projection = WorkspaceProjection.model_validate(
        {
            "session_id": new_session_id(),
            "workspace_root": "/tmp/workspace-suspended",
            "prepared_at": created_at,
            "updated_at": created_at,
            "current_sequence": 4,
            "status": WorkspaceStatus.SUSPENDED,
            "runtime_name": "local",
            "snapshot_id": "snap-002",
            "snapshot_path": "/tmp/snapshots/snap-002",
        }
    )

    store.save_workspace(projection)
    loaded = store.get_workspace(projection.session_id)

    assert loaded is not None
    assert loaded.runtime_name == "local"
    assert loaded.snapshot_id == "snap-002"
    assert loaded.snapshot_path == "/tmp/snapshots/snap-002"


def test_session_policy_profile_for_session_uses_workspace_policy(tmp_path: Path) -> None:
    store = SQLiteWorkspaceProjectionStore(tmp_path / "workspace.db")
    created_at = datetime(2026, 6, 29, 19, 0, tzinfo=UTC)
    projection = WorkspaceProjection.model_validate(
        {
            "session_id": new_session_id(),
            "workspace_root": "/tmp/workspace-policy",
            "prepared_at": created_at,
            "updated_at": created_at,
            "current_sequence": 1,
            "status": WorkspaceStatus.RUNNING,
            "policy_profile": "full_access",
        }
    )
    store.save_workspace(projection)

    assert (
        session_policy_profile_for_session(tmp_path / "workspace.db", projection.session_id)
        == "full_access"
    )


def test_session_policy_profile_for_session_defaults_when_workspace_missing(
    tmp_path: Path,
) -> None:
    assert (
        session_policy_profile_for_session(
            tmp_path / "workspace.db",
            SessionId(UUID("00000000-0000-0000-0000-000000000001")),
        )
        == "workspace_write"
    )

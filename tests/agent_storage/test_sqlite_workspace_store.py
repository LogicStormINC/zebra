from datetime import UTC, datetime
from pathlib import Path

from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import SQLiteWorkspaceProjectionStore


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

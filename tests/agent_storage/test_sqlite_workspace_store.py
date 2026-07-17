import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.tool_profiles import ToolProfile
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
            "tool_profile": ToolProfile.GENERAL,
            "network_profile": "domain-allowlist",
            "network_allowlist": ("docs.example.com", "api.example.com"),
            "last_attempt_number": 1,
            "runtime_name": "local",
            "runtime_engine": "docker",
            "runtime_image": "zebra/runtime@sha256:" + "a" * 64,
            "runtime_spec_digest": "b" * 64,
            "runtime_network_enforcement": "container-network-none",
            "runtime_workspace_writable": True,
            "snapshot_id": "snap-001",
            "snapshot_path": "/tmp/snapshots/snap-001",
        }
    )

    store.save_workspace(projection)
    loaded = store.get_workspace(projection.session_id)

    assert loaded == projection


def test_sqlite_workspace_projection_store_migrates_legacy_profile(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-workspace.db"
    session_id = new_session_id()
    created_at = datetime(2026, 6, 29, 18, 35, tzinfo=UTC).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE workspace_projections (
                session_id TEXT PRIMARY KEY,
                workspace_root TEXT NOT NULL,
                prepared_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                current_sequence INTEGER NOT NULL,
                status TEXT NOT NULL,
                policy_profile TEXT,
                last_attempt_number INTEGER,
                runtime_name TEXT,
                snapshot_id TEXT,
                snapshot_path TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO workspace_projections (
                session_id, workspace_root, prepared_at, updated_at,
                current_sequence, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(session_id), "/tmp/legacy", created_at, created_at, 1, "prepared"),
        )

    loaded = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)

    assert loaded is not None
    assert loaded.tool_profile is ToolProfile.CODING
    assert loaded.network_profile.value == "none"
    assert loaded.network_allowlist == ()


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

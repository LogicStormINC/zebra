import json
from pathlib import Path

import pytest
from agent_core.domain.workspaces import WorkspaceStatus
from agent_storage import (
    SQLiteWorkspaceProjectionStore,
)
from worker_execution_support import (
    _assistant_only_gateway,
    _build_execution_service,
    _created_at,
    _seed_ready_session,
)
from zebra_agent_worker import (
    SessionControlService,
)
from zebra_agent_worker.execution import WorkerExecutionError


def test_worker_execution_service_updates_workspace_projection_lifecycle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)

    assert workspace is not None
    assert workspace.workspace_root == str(tmp_path.resolve())
    assert workspace.status is WorkspaceStatus.COMPLETED
    assert workspace.last_attempt_number == 1


def test_worker_execution_service_restores_suspended_workspace_before_running(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    original_workspace = tmp_path / "workspace"
    original_workspace.mkdir()
    (original_workspace / "note.txt").write_text("before suspend\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, original_workspace)
    suspended = SessionControlService(database_path).suspend_session(session_id)
    (original_workspace / "note.txt").write_text("after suspend\n", encoding="utf-8")

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)

    assert workspace is not None
    assert workspace.status is WorkspaceStatus.COMPLETED
    assert workspace.workspace_root != str(original_workspace.resolve())
    assert (Path(workspace.workspace_root) / "note.txt").read_text(encoding="utf-8") == (
        "before suspend\n"
    )
    assert workspace.snapshot_id is None
    assert workspace.snapshot_path is None
    assert suspended.workspace.snapshot_path is not None
    assert Path(suspended.workspace.snapshot_path).exists() is False


def test_worker_execution_service_rejects_incompatible_suspended_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    session_id = _seed_ready_session(database_path, workspace_root)
    suspended = SessionControlService(database_path).suspend_session(session_id)
    assert suspended.workspace.snapshot_path is not None
    manifest_path = Path(suspended.workspace.snapshot_path) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_name"] = "remote"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    with pytest.raises(WorkerExecutionError, match="snapshot is incompatible"):
        _build_execution_service(database_path).execute_session(
            session_id,
            worker_id="worker-a",
            executed_at=_created_at(),
        )

    restored_workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)
    assert restored_workspace is not None
    assert restored_workspace.status is WorkspaceStatus.SUSPENDED

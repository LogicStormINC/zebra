import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import SessionId, new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.domain.tools import ToolCall
from agent_core.domain.workspaces import WorkspaceStatus
from agent_storage import (
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteModelCallStore,
    SQLiteProjectionStore,
    SQLiteToolRunStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_worker import (
    SessionClaimService,
    SessionControlService,
    SessionExecutionService,
    SessionRecoveryService,
    SessionResumeService,
)
from zebra_agent_worker.execution import WorkerExecutionError


def test_worker_execution_service_completes_ready_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == "Worker completed the session."
    assert SQLiteLeaseStore(database_path).get(session_id) is None
    model_calls = SQLiteModelCallStore(database_path).list_for_session(session_id)
    assert len(model_calls) == 1
    assert isinstance(model_calls[0], ModelCallRecord)


def test_worker_execution_service_indexes_tool_run(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "worker.db"
    (tmp_path / "README.md").write_text("worker readme\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _tool_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    tool_runs = SQLiteToolRunStore(database_path).list_for_session(session_id)
    assert result.session.status is SessionStatus.COMPLETED
    assert len(tool_runs) == 1
    assert isinstance(tool_runs[0], ToolRunRecord)
    assert tool_runs[0].tool_name == "files.read"
    assert tool_runs[0].status == "executed"


def _build_execution_service(database_path: Path) -> SessionExecutionService:
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )
    return SessionExecutionService(
        database_path=database_path,
        claim_service=claim_service,
        resume_service=SessionResumeService(claim_service),
        settings=_settings(database_path),
    )


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued worker task",
            user_input="Continue the queued task.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(bootstrap.session.session_id)
    return bootstrap.session.session_id


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


def _settings(database_path: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )


def _assistant_only_gateway(*, settings: ZebraAgentSettings) -> ScriptedModelGateway:
    del settings
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Worker completed the session.",
                        created_at=_created_at(),
                    ),
                    call_metadata=ModelCallMetadata(
                        provider="test",
                        model_name="test-model",
                        usage=ModelUsage(total_tokens=7),
                    ),
                )
            ),
        )
    )


def _tool_gateway(*, settings: ZebraAgentSettings) -> ScriptedModelGateway:
    del settings
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Reading README.",
                        created_at=_created_at(),
                    ),
                    tool_calls=(
                        ToolCall(
                            tool_call_id=new_tool_call_id(),
                            name="files.read",
                            arguments={"path": "README.md"},
                            created_at=_created_at(),
                        ),
                    ),
                    call_metadata=ModelCallMetadata(
                        provider="test",
                        model_name="test-model",
                        usage=ModelUsage(total_tokens=9),
                    ),
                )
            ),
        )
    )


def _created_at() -> datetime:
    return datetime(2026, 6, 22, 14, 0, tzinfo=UTC)

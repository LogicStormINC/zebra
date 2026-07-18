from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelUsage,
)
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.tools import ToolCall
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import (
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from cli_run_support import (
    FakeGateway,
    _created_at,
    _seed_ready_session,
    _settings,
)
from zebra_agent_cli.cli import execute
from zebra_agent_config import ZebraAgentSettings


def test_cli_resume_command_reads_local_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Resume me")
    )

    result = execute(["resume", str(session.session_id), "--database", str(database_path)])

    assert result.command == "resume"
    assert result.payload["session_id"] == str(session.session_id)
    assert result.payload["database"] == str(database_path)
    assert result.payload["title"] == "Resume me"
    assert result.payload["status"] == SessionStatus.CREATED.value
    assert result.payload["current_sequence"] == 0

def test_cli_resume_read_includes_workspace_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Resume workspace").model_copy(
            update={
                "status": SessionStatus.SUSPENDED,
                "current_sequence": 4,
            }
        )
    )
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        WorkspaceProjection.model_validate(
            {
                "session_id": session.session_id,
                "workspace_root": str(tmp_path.resolve()),
                "prepared_at": _created_at(),
                "updated_at": _created_at(),
                "current_sequence": 4,
                "status": WorkspaceStatus.SUSPENDED,
                "policy_profile": "workspace_write",
                "last_attempt_number": 1,
                "runtime_name": "local",
                "snapshot_id": "snap-cli-1",
                "snapshot_path": "/tmp/zebra-agent-runtime/snap-cli-1",
            }
        )
    )

    result = execute(["resume", str(session.session_id), "--database", str(database_path)])

    assert result.payload["workspace"] == {
        "workspace_root": str(tmp_path.resolve()),
        "tool_profile": "coding",
        "network_profile": "none",
        "network_allowlist": [],
        "status": "suspended",
        "current_sequence": 4,
        "prepared_at": _created_at().isoformat(),
        "updated_at": _created_at().isoformat(),
        "policy_profile": "workspace_write",
        "last_attempt_number": 1,
        "runtime_name": "local",
        "snapshot": {
            "runtime_name": "local",
            "snapshot_id": "snap-cli-1",
            "snapshot_path": "/tmp/zebra-agent-runtime/snap-cli-1",
        },
    }

def test_cli_suspend_command_marks_session_suspended(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, tmp_path)

    result = execute(["suspend", str(session_id), "--database", str(database_path)])

    updated_session = SQLiteProjectionStore(database_path).get_session(session_id)
    assert result.command == "suspend"
    assert result.payload["suspended"] is True
    assert result.payload["status"] == "suspended"
    assert updated_session is not None
    assert updated_session.status is SessionStatus.SUSPENDED

def test_cli_resume_command_execute_runs_worker_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, tmp_path)

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Resume execution complete.",
                    created_at=_created_at(),
                ),
                call_metadata=ModelCallMetadata(
                    provider="test",
                    model_name="test-model",
                    latency_ms=5,
                    usage=ModelUsage(total_tokens=6),
                ),
            )
        )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        fake_build_model_gateway,
    )

    result = execute(
        [
            "resume",
            str(session_id),
            "--execute",
            "--worker-id",
            "worker-a",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    updated_session = SQLiteProjectionStore(database_path).get_session(session_id)
    assert result.command == "resume"
    assert result.payload["executed"] is True
    assert result.payload["worker_id"] == "worker-a"
    assert result.payload["status"] == SessionStatus.COMPLETED.value
    assert result.payload["assistant_message"] == "Resume execution complete."
    assert result.payload["trace"] == [
        {
            "attempt_number": 1,
            "assistant_message": "Resume execution complete.",
            "tools": [],
        }
    ]
    assert updated_session is not None
    assert updated_session.status is SessionStatus.COMPLETED
    assert SQLiteLeaseStore(database_path).get(session_id) is None

def test_cli_resume_command_execute_restores_suspended_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("before suspend\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace)
    execute(["suspend", str(session_id), "--database", str(database_path)])
    (workspace / "README.md").write_text("after suspend\n", encoding="utf-8")

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Resume execution complete.",
                    created_at=_created_at(),
                )
            )
        )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        fake_build_model_gateway,
    )

    result = execute(
        [
            "resume",
            str(session_id),
            "--execute",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    workspace_projection = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)
    assert result.payload["status"] == SessionStatus.COMPLETED.value
    assert workspace_projection is not None
    assert workspace_projection.workspace_root != str(workspace.resolve())

def test_cli_resume_command_execute_reports_tool_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    (tmp_path / "README.md").write_text("resume readme\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, tmp_path)

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Reading README on resume.",
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
            )
        )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        fake_build_model_gateway,
    )

    result = execute(
        [
            "resume",
            str(session_id),
            "--execute",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    trace = result.payload["trace"]
    assert len(trace) == 1
    assert trace[0]["attempt_number"] == 1
    assert trace[0]["assistant_message"] == "Tool result: resume readme"
    tool = trace[0]["tools"][0]
    assert tool["tool_name"] == "files.read"
    assert tool["status"] == "executed"
    assert tool["arguments"] == {"path": "README.md"}
    assert tool["output"] == "resume readme\n"
    assert tool["policy_decision"] == "allow"
    metadata = tool["metadata"]
    assert metadata["path"] == "README.md"
    assert metadata["byte_count"] == 14
    assert metadata["truncated"] is False
    assert metadata["artifact_uri"].startswith("file://")
    assert metadata["output_envelope"]["checksum"] == metadata["output_sha256"]

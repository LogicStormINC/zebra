import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import zebra_agent_cli.cli as cli_module
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.tools import ToolCall
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import (
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_cli.cli import execute, main
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_cli_run_command_creates_local_session(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "sessions.sqlite"

    assert (
        main(
            [
                "run",
                "Fix tests",
                "--title",
                "Fix failing tests",
                "--database",
                str(database_path),
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    session_id = SessionId(UUID(output["session_id"]))
    session = SQLiteProjectionStore(database_path).get_session(session_id)
    events = SQLiteEventStore(database_path).list_for_session(session_id)

    assert output["command"] == "run"
    assert output["prompt"] == "Fix tests"
    assert output["executed"] is False
    assert output["status"] == SessionStatus.READY.value
    assert output["title"] == "Fix failing tests"
    assert output["workspace"] == "."
    assert output["database"] == str(database_path)
    assert session is not None
    assert session.title == "Fix failing tests"
    assert session.status is SessionStatus.READY
    assert len(events) == 3
    assert events[0].event_type is EventType.SESSION_CREATED
    assert events[0].payload == {"title": "Fix failing tests"}
    assert events[1].event_type is EventType.USER_MESSAGE_RECEIVED
    assert events[1].payload == {"content": "Fix tests"}
    assert events[2].event_type is EventType.TASK_PREPARED
    assert events[2].payload["workspace_root"] == str(Path(".").resolve())


def test_cli_run_command_uses_settings_database_by_default(tmp_path: Path) -> None:
    database_path = tmp_path / "configured.sqlite"

    result = execute(
        ["run", "Use configured database"],
        settings=_settings(database_path),
    )
    session = SQLiteProjectionStore(database_path).get_session(
        SessionId(UUID(str(result.payload["session_id"])))
    )
    events = SQLiteEventStore(database_path).list_for_session(
        SessionId(UUID(str(result.payload["session_id"])))
    )

    assert result.payload["database"] == str(database_path)
    assert session is not None
    assert len(events) == 3


def test_cli_run_command_database_option_overrides_settings(tmp_path: Path) -> None:
    configured_path = tmp_path / "configured.sqlite"
    explicit_path = tmp_path / "explicit.sqlite"

    result = execute(
        [
            "run",
            "Use explicit database",
            "--database",
            str(explicit_path),
        ],
        settings=_settings(configured_path),
    )

    assert result.payload["database"] == str(explicit_path)
    assert SQLiteProjectionStore(explicit_path).get_session(
        SessionId(UUID(str(result.payload["session_id"])))
    ) is not None
    assert not configured_path.exists()


def test_cli_run_command_execute_persists_harness_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"

    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Repository inspected.",
                    created_at=_created_at(),
                ),
                call_metadata=ModelCallMetadata(
                    provider="test",
                    model_name="test-model",
                    latency_ms=7,
                    usage=ModelUsage(total_tokens=12),
                ),
            )
        )

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)
    monkeypatch.setattr("zebra_agent_cli.execution.build_model_gateway", fake_build_model_gateway)

    result = execute(
        [
            "run",
            "Inspect the repository",
            "--execute",
            "--workspace",
            str(tmp_path),
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    session_id = SessionId(UUID(str(result.payload["session_id"])))
    session = SQLiteProjectionStore(database_path).get_session(session_id)
    events = SQLiteEventStore(database_path).list_for_session(session_id)

    assert result.command == "run"
    assert result.payload["executed"] is True
    assert result.payload["status"] == SessionStatus.COMPLETED.value
    assert result.payload["assistant_message"] == "Repository inspected."
    assert result.payload["policy_profile"] == "workspace_write"
    assert result.payload["workspace_root"] == str(tmp_path.resolve())
    assert [event.event_type for event in events] == [
        EventType.SESSION_CREATED,
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TASK_PREPARED,
        EventType.HARNESS_ATTEMPT_STARTED,
        EventType.MODEL_RESPONSE_RECEIVED,
        EventType.PLAN_PROPOSED,
        EventType.SESSION_COMPLETED,
    ]
    assert session is not None
    assert session.status is SessionStatus.COMPLETED


def test_cli_run_command_execute_runs_file_read_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    (tmp_path / "README.md").write_text("workspace readme\n", encoding="utf-8")

    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="I will read the README.",
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

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)
    monkeypatch.setattr("zebra_agent_cli.execution.build_model_gateway", fake_build_model_gateway)

    result = execute(
        [
            "run",
            "Read the README",
            "--execute",
            "--workspace",
            str(tmp_path),
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload["status"] == SessionStatus.COMPLETED.value
    assert result.payload["trace"] == [
        {
            "attempt_number": 1,
            "assistant_message": "I will read the README.",
            "tools": [
                {
                    "tool_name": "files.read",
                    "status": "executed",
                    "arguments": {"path": "README.md"},
                    "output": "workspace readme\n",
                    "metadata": {
                        "path": "README.md",
                        "byte_count": 17,
                        "truncated": False,
                    },
                    "policy_decision": "allow",
                }
            ],
        }
    ]


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
        "status": "suspended",
        "current_sequence": 4,
        "prepared_at": _created_at().isoformat(),
        "updated_at": _created_at().isoformat(),
        "policy_profile": "workspace_write",
        "last_attempt_number": 1,
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

    assert result.payload["trace"] == [
        {
            "attempt_number": 1,
            "assistant_message": "Reading README on resume.",
            "tools": [
                {
                    "tool_name": "files.read",
                    "status": "executed",
                    "arguments": {"path": "README.md"},
                    "output": "resume readme\n",
                    "metadata": {
                        "path": "README.md",
                        "byte_count": 14,
                        "truncated": False,
                    },
                    "policy_decision": "allow",
                }
            ],
        }
    ]


def test_cli_inspect_command_reads_local_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Inspect me")
    )

    result = execute(["inspect", str(session.session_id), "--database", str(database_path)])

    assert result.command == "inspect"
    assert result.payload["session_id"] == str(session.session_id)
    assert result.payload["title"] == "Inspect me"


def test_cli_inspect_command_includes_workspace_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Inspect workspace").model_copy(
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
                "runtime_name": "local",
                "snapshot_id": "snap-cli-2",
                "snapshot_path": "/tmp/zebra-agent-runtime/snap-cli-2",
            }
        )
    )

    result = execute(["inspect", str(session.session_id), "--database", str(database_path)])

    assert result.payload["workspace"] == {
        "workspace_root": str(tmp_path.resolve()),
        "status": "suspended",
        "current_sequence": 4,
        "prepared_at": _created_at().isoformat(),
        "updated_at": _created_at().isoformat(),
        "snapshot": {
            "runtime_name": "local",
            "snapshot_id": "snap-cli-2",
            "snapshot_path": "/tmp/zebra-agent-runtime/snap-cli-2",
        },
    }


def test_cli_inspect_command_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "inspect",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "database": str(database_path),
        "status": "not_found",
    }


def test_cli_approve_command_records_granted_decision(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    waiting = Session.create(title="Needs approval").model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "current_sequence": 2,
        }
    )
    SQLiteProjectionStore(database_path).save_session(waiting)

    result = execute(
        [
            "approve",
            str(waiting.session_id),
            "--decision",
            "approve",
            "--reason",
            "safe",
            "--database",
            str(database_path),
        ]
    )
    events = SQLiteEventStore(database_path).list_for_session(waiting.session_id)
    session = SQLiteProjectionStore(database_path).get_session(waiting.session_id)

    assert result.payload["session_id"] == str(waiting.session_id)
    assert result.payload["decision"] == "approve"
    assert result.payload["event_type"] == EventType.APPROVAL_GRANTED.value
    assert result.payload["sequence"] == 3
    assert result.payload["status"] == SessionStatus.RUNNING.value
    assert events[0].event_type is EventType.APPROVAL_GRANTED
    assert session is not None
    assert session.status is SessionStatus.RUNNING


def test_cli_approve_command_rejects_non_waiting_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No approval needed")
    )

    result = execute(
        [
            "approve",
            str(session.session_id),
            "--decision",
            "reject",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload["status"] == "invalid_state"
    assert "waiting approval" in str(result.payload["reason"])


def test_cli_approve_requires_valid_decision() -> None:
    with pytest.raises(SystemExit):
        execute(
            [
                "approve",
                "00000000-0000-0000-0000-000000000001",
                "--decision",
                "maybe",
            ]
        )


def test_cli_model_command_uses_configured_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        assert settings.model.provider == "test"
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Gateway response",
                    created_at=_created_at(),
                ),
                call_metadata=ModelCallMetadata(
                    provider="test",
                    model_name="test-model",
                    latency_ms=42,
                    usage=ModelUsage(
                        input_tokens=3,
                        output_tokens=5,
                        total_tokens=8,
                    ),
                ),
            )
        )

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)

    result = execute(["model", "Hello"], settings=_settings(Path(":memory:")))

    assert result.command == "model"
    assert result.payload == {
        "prompt": "Hello",
        "response": "Gateway response",
        "provider": "test",
        "model_name": "test-model",
        "latency_ms": 42,
        "input_tokens": 3,
        "output_tokens": 5,
        "total_tokens": 8,
        "tool_calls": [],
    }


def test_cli_model_command_reports_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Tool calls proposed.",
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

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)

    result = execute(["model", "Read the README"], settings=_settings(Path(":memory:")))

    assert result.payload["tool_calls"] == [
        {
            "name": "files.read",
            "arguments": {"path": "README.md"},
        }
    ]


def test_cli_model_command_surfaces_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        raise ValueError("missing API key in environment variable TEST_API_KEY")

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)

    with pytest.raises(ValueError, match="missing API key"):
        execute(["model", "Hello"], settings=_settings(Path(":memory:")))


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


def _created_at() -> datetime:
    return datetime(2026, 6, 22, 12, 30, tzinfo=UTC)


class FakeGateway:
    def __init__(self, *, completion: ModelCompletion) -> None:
        self._completion = completion

    def complete(self, messages: list[SessionMessage]) -> ModelCompletion:
        assert len(messages) == 1
        assert messages[0].role is MessageRole.USER
        return self._completion


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService

    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Resume task",
            user_input="Continue the queued session.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id

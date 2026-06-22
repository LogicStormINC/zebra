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
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
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
    assert output["status"] == SessionStatus.CREATED.value
    assert output["title"] == "Fix failing tests"
    assert output["workspace"] == "."
    assert output["database"] == str(database_path)
    assert session is not None
    assert session.title == "Fix failing tests"
    assert session.status is SessionStatus.CREATED
    assert len(events) == 1
    assert events[0].event_type is EventType.SESSION_CREATED
    assert events[0].payload == {"title": "Fix failing tests"}


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
    assert len(events) == 1


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


def test_cli_inspect_command_reads_local_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Inspect me")
    )

    result = execute(["inspect", str(session.session_id), "--database", str(database_path)])

    assert result.command == "inspect"
    assert result.payload["session_id"] == str(session.session_id)
    assert result.payload["title"] == "Inspect me"


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

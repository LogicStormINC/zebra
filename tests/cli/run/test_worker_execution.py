from pathlib import Path
from uuid import UUID

import pytest
import zebra_agent_cli.cli as cli_module
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import MemoryId, SessionId, new_message_id, new_tool_call_id
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelToolDefinition,
    ModelUsage,
)
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCall
from agent_storage import (
    SQLiteEventStore,
    SQLiteMemoryStore,
    SQLiteProjectionStore,
)
from cli_run_support import (
    FakeGateway,
    _created_at,
    _settings,
)
from zebra_agent_cli.cli import execute
from zebra_agent_config import ZebraAgentSettings


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
            "assistant_message": "Tool result: workspace readme",
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

def test_cli_run_command_execute_injects_confirmed_memory_into_system_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    requests: list[tuple[SessionMessage, ...]] = []
    SQLiteMemoryStore(database_path).upsert(
        MemoryRecord(
            memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000142")),
            memory_type=MemoryType.PROCEDURE,
            text="Run make check before push.",
            confidence=0.9,
            status=MemoryStatus.CONFIRMED,
            visibility=MemoryVisibility.REPO,
            repo_id=str(tmp_path.resolve()),
            source_session_id=SessionId(UUID("00000000-0000-0000-0000-000000000043")),
            created_at=_created_at(),
            updated_at=_created_at(),
        )
    )

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings

        class RecordingGateway:
            def complete(
                self,
                messages: list[SessionMessage],
                *,
                tools: tuple[ModelToolDefinition, ...] = (),
            ) -> ModelCompletion:
                assert tools
                requests.append(tuple(messages))
                return ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="CLI execution complete.",
                        created_at=_created_at(),
                    ),
                    call_metadata=ModelCallMetadata(
                        provider="test",
                        model_name="test-model",
                        latency_ms=7,
                        usage=ModelUsage(total_tokens=12),
                    ),
                )

        return RecordingGateway()

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)
    monkeypatch.setattr("zebra_agent_cli.execution.build_model_gateway", fake_build_model_gateway)

    result = execute(
        [
            "run",
            "Inspect workspace",
            "--title",
            "CLI execute with memory",
            "--workspace",
            str(tmp_path),
            "--execute",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload["executed"] is True
    assert requests
    assert requests[0][0].role is MessageRole.SYSTEM
    assert "Procedure 1" in requests[0][0].content
    assert "Run make check before push." in requests[0][0].content

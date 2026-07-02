from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.memories import MemoryType
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCall
from agent_core.ports.context_compiler import ConfirmedMemoryInput
from agent_runtime import run_local_harness


def test_run_local_harness_completes_without_tool_calls(tmp_path) -> None:
    result = run_local_harness(
        prompt="Summarize the repository.",
        title="Runtime harness test",
        workspace_root=tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Repository summary.",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        ),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == "Repository summary."


def test_run_local_harness_executes_builtin_file_read(tmp_path) -> None:
    (tmp_path / "README.md").write_text("runtime readme\n", encoding="utf-8")
    result = run_local_harness(
        prompt="Read the repository README.",
        title="Runtime harness tool test",
        workspace_root=tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Inspecting README.",
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
                ),
            )
        ),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["tool_name"] == "files.read"
    assert result.attempt_result.metadata["tool_output"] == "runtime readme\n"


def test_run_local_harness_injects_confirmed_memory_into_system_prompt(tmp_path) -> None:
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Repository summary.",
                        created_at=_created_at(),
                    )
                )
            ),
        )
    )

    run_local_harness(
        prompt="Summarize the repository.",
        title="Runtime memory prompt test",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
        confirmed_memories=(
            ConfirmedMemoryInput(
                memory_type=MemoryType.PROCEDURE,
                text="Run make check before push.",
            ),
        ),
    )

    assert gateway.requests[0][0].role is MessageRole.SYSTEM
    assert "Procedure 1" in gateway.requests[0][0].content
    assert "Run make check before push." in gateway.requests[0][0].content


def _created_at() -> datetime:
    return datetime(2026, 6, 22, 13, 0, tzinfo=UTC)

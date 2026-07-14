from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.memories import MemoryType
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCall
from agent_core.ports.context_compiler import ConfirmedMemoryInput
from agent_runtime import LocalToolGateway, run_local_harness
from agent_tools import McpProxyRequest, McpProxyResponse


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
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="The README contains: runtime readme",
                            created_at=_created_at(),
                        )
                    )
                ),
            ),
        ),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["tool_name"] == "files.read"
    assert result.attempt_result.metadata["tool_output"] == "runtime readme\n"
    assert result.attempt_result.metadata["assistant_message"] == (
        "The README contains: runtime readme"
    )
    assert result.run_result.model_calls_used == 2


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


def test_run_local_harness_advertises_its_executable_tools(tmp_path) -> None:
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="No tool needed.",
                        created_at=_created_at(),
                    )
                )
            ),
        )
    )

    run_local_harness(
        prompt="Inspect the workspace.",
        title="Runtime tool discovery test",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
    )

    tools = gateway.tool_requests[0]
    assert tuple(tool.name for tool in tools) == (
        "agent.research",
        "command.run",
        "files.read",
        "git.status",
        "patch.apply",
        "tests.run",
    )
    file_read = next(tool for tool in tools if tool.name == "files.read")
    assert file_read.parameters["required"] == ["path"]


def test_local_tool_gateway_exposes_only_parallel_safe_builtins(tmp_path) -> None:
    gateway = LocalToolGateway(tmp_path.resolve())

    assert gateway.parallel_safe_tools == frozenset({"files.read", "git.status"})


def test_local_tool_gateway_advertises_enabled_minimax_image_tool(tmp_path) -> None:
    transport = _FakeMcpTransport()
    gateway = LocalToolGateway(tmp_path.resolve(), mcp_proxy_transport=transport)

    names = tuple(tool.name for tool in gateway.model_tools)

    assert "mcp.minimax.understand_image" in names
    assert "mcp.minimax.understand_image" not in gateway.parallel_safe_tools


def test_run_local_harness_executes_preapproved_minimax_image_tool(tmp_path) -> None:
    transport = _FakeMcpTransport()
    result = run_local_harness(
        prompt="Read the screenshot.",
        title="Runtime image tool test",
        workspace_root=tmp_path.resolve(),
        model_gateway=ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Reading the screenshot.",
                            created_at=_created_at(),
                        ),
                        tool_calls=(
                            ToolCall(
                                tool_call_id=new_tool_call_id(),
                                name="mcp.minimax.understand_image",
                                arguments={
                                    "prompt": "Extract visible transactions.",
                                    "image_source": "broker.png",
                                },
                                created_at=_created_at(),
                            ),
                        ),
                    )
                ),
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="The image was read.",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        ),
        mcp_proxy_transport=transport,
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["tool_name"] == "mcp.minimax.understand_image"
    assert result.attempt_result.metadata["tool_output"] == "understand_image"
    assert result.attempt_result.metadata["assistant_message"] == "The image was read."


class _FakeMcpTransport:
    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        return McpProxyResponse(output=request.target.tool_name)


def _created_at() -> datetime:
    return datetime(2026, 6, 22, 13, 0, tzinfo=UTC)

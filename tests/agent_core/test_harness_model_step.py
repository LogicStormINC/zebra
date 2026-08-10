from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_context import LocalContextCompiler
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.memories import MemoryType
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelContextWindow,
    ModelTextDelta,
    ModelToolDefinition,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessModelStep, HarnessTask
from agent_core.harness.context_window import ContextWindowExceededError
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput
from agent_core.ports.model_gateway import ModelResponseRejectedError


class StaticContextCompiler:
    def __init__(self) -> None:
        self.budgets: list[int] = []

    def build_system_prompt(
        self,
        *,
        task_input: str,
        workspace_root: Path,
        max_tokens: int,
        runtime_evidence: tuple[RuntimeEvidenceInput, ...] = (),
        confirmed_memories: tuple[ConfirmedMemoryInput, ...] = (),
    ) -> str | None:
        self.budgets.append(max_tokens)
        return (
            f"workspace={workspace_root.name};"
            f" task={task_input};"
            f" budget={max_tokens}"
            f" evidence={len(runtime_evidence)}"
            f" memories={len(confirmed_memories)}"
        )


RESEARCH_TOOL = ModelToolDefinition(
    name="agent.research",
    description="Delegate bounded research.",
    parameters={"type": "object", "properties": {}},
)
PLAN_TOOL = ModelToolDefinition(
    name="agent.plan",
    description="Maintain the durable task plan.",
    parameters={"type": "object", "properties": {}},
)


def test_delegation_guidance_follows_effective_tool_manifest() -> None:
    created_at = datetime(2026, 7, 19, 20, 0, tzinfo=UTC)
    task = HarnessTask(title="Simple", user_input="What is 1 + 1?")

    parent_messages = HarnessModelStep(
        available_tools=(RESEARCH_TOOL,)
    ).build_initial_messages(task, created_at=created_at)
    direct_messages = HarnessModelStep().build_initial_messages(
        task, created_at=created_at
    )

    assert parent_messages[0].role is MessageRole.SYSTEM
    assert "Answer directly" in parent_messages[0].content
    assert "delegation_reason" in parent_messages[0].content
    assert "Plan activation" not in parent_messages[0].content
    assert [message.role for message in direct_messages] == [MessageRole.USER]


def test_plan_activation_guidance_follows_effective_tool_manifest() -> None:
    created_at = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)
    task = HarnessTask(title="Investigate", user_input="Investigate a complex issue.")

    planned_messages = HarnessModelStep(
        available_tools=(PLAN_TOOL, RESEARCH_TOOL)
    ).build_initial_messages(task, created_at=created_at)
    direct_messages = HarnessModelStep().build_initial_messages(
        task, created_at=created_at
    )

    assert planned_messages[0].role is MessageRole.SYSTEM
    assert "must first call agent.plan" in planned_messages[0].content
    assert "Simple one-step tasks may proceed without a Plan" in planned_messages[0].content
    assert "verify them with at least one relevant authoritative typed read" in (
        planned_messages[0].content
    )
    assert "delegation_reason" in planned_messages[0].content
    assert planned_messages[-1].role is MessageRole.USER
    assert [message.role for message in direct_messages] == [MessageRole.USER]


def test_harness_model_step_injects_compiled_context_as_system_message(
    tmp_path: Path,
) -> None:
    created_at = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will inspect the repository.",
                        created_at=created_at,
                    )
                )
            ),
        )
    )

    step = HarnessModelStep(context_compiler=StaticContextCompiler())
    step.request_initial_completion(
        HarnessTask(
            title="Inspect repo",
            user_input="Please inspect the repository.",
            workspace_root=workspace.resolve(),
            context_token_budget=120,
            confirmed_memories=(
                ConfirmedMemoryInput(
                    memory_type=MemoryType.PROCEDURE,
                    text="Run make check before push.",
                ),
            ),
        ),
        gateway,
        created_at=created_at,
    )

    assert len(gateway.requests) == 1
    assert gateway.requests[0][0].role is MessageRole.SYSTEM
    assert "workspace=workspace" in gateway.requests[0][0].content
    assert "evidence=0" in gateway.requests[0][0].content
    assert "memories=1" in gateway.requests[0][0].content
    assert gateway.requests[0][1].role is MessageRole.USER


def test_active_projection_uses_the_compaction_reserve_without_changing_other_tasks(
    tmp_path: Path,
) -> None:
    class ReserveGateway:
        context_window = ModelContextWindow(compaction_reserve_tokens=640)

        def complete(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
        ) -> ModelCompletion:
            del messages, tools
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="captured",
                    created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
                )
            )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    compiler = StaticContextCompiler()
    step = HarnessModelStep(context_compiler=compiler)
    gateway = ReserveGateway()
    active_projection = RuntimeEvidenceInput(
        kind="session_handoff",
        summary="Continue the validated source objective.",
        metadata={"handoff_source": "active_projection"},
    )

    step.request_initial_completion(
        HarnessTask(
            title="Projected child",
            user_input="Continue the child task.",
            workspace_root=workspace.resolve(),
            context_token_budget=200,
            runtime_evidence=(active_projection,),
        ),
        gateway,
    )
    step.request_initial_completion(
        HarnessTask(
            title="Ordinary task",
            user_input="Continue the ordinary task.",
            workspace_root=workspace.resolve(),
            context_token_budget=200,
        ),
        gateway,
    )

    assert compiler.budgets == [640, 200]


def test_checkpoint_handoff_uses_compaction_reserve_and_keeps_latest_user_last(
    tmp_path: Path,
) -> None:
    class CapturingGateway:
        context_window = ModelContextWindow(compaction_reserve_tokens=640)

        def __init__(self) -> None:
            self.requests: list[list[SessionMessage]] = []

        def complete(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
        ) -> ModelCompletion:
            del tools
            self.requests.append(list(messages))
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Ready to continue.",
                    created_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
                )
            )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = "CHECKPOINT-CONTINUITY-MUST-REACH-MODEL"
    gateway = CapturingGateway()

    HarnessModelStep(context_compiler=LocalContextCompiler()).request_initial_completion(
        HarnessTask(
            title="Checkpoint continuation",
            user_input="FOLLOW-UP-USER-LAST",
            workspace_root=workspace.resolve(),
            context_token_budget=200,
            runtime_evidence=(
                RuntimeEvidenceInput(
                    kind="session_handoff",
                    summary=marker,
                    details=("Skill continuity: " + "checkpoint evidence " * 120,),
                    metadata={"handoff_source": "checkpoint"},
                ),
            ),
        ),
        gateway,
    )

    request = gateway.requests[0]
    assert marker in request[0].content
    assert request[-1].role is MessageRole.USER
    assert request[-1].content == "FOLLOW-UP-USER-LAST"
    assert all(message.role is not MessageRole.TOOL for message in request)


def test_active_projection_compilation_keeps_the_model_request_hard_gate(
    tmp_path: Path,
) -> None:
    class SizedContextCompiler:
        def build_system_prompt(
            self,
            *,
            task_input: str,
            workspace_root: Path,
            max_tokens: int,
            runtime_evidence: tuple[RuntimeEvidenceInput, ...] = (),
            confirmed_memories: tuple[ConfirmedMemoryInput, ...] = (),
        ) -> str | None:
            del task_input, workspace_root, runtime_evidence, confirmed_memories
            return "x" * (max_tokens * 4)

    class SmallGateway:
        context_window = ModelContextWindow(
            context_tokens=1_000,
            max_output_tokens=100,
            compaction_reserve_tokens=500,
            protocol_reserve_tokens=100,
        )

        def complete(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
        ) -> ModelCompletion:
            raise AssertionError("the hard gate must run before the model call")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ContextWindowExceededError):
        HarnessModelStep(context_compiler=SizedContextCompiler()).request_initial_completion(
            HarnessTask(
                title="Projected child",
                user_input="Continue the child task.",
                workspace_root=workspace.resolve(),
                context_token_budget=200,
                runtime_evidence=(
                    RuntimeEvidenceInput(
                        kind="session_handoff",
                        summary="Continue the validated source objective.",
                        metadata={"handoff_source": "active_projection"},
                    ),
                ),
            ),
            SmallGateway(),
        )


def test_tool_result_message_keeps_structured_status_and_operation_key() -> None:
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="mcp.minimax.understand_image",
        arguments={"image_source": "receipts/statement.png", "prompt": "Read totals."},
        created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        provider_call_id="image-call",
    )
    messages: list[SessionMessage] = []

    HarnessModelStep.append_tool_result(
        messages,
        tool_call=tool_call,
        tool_result=ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED,
            output="timeout",
            metadata={"operation_key": "opaque-image-operation"},
        ),
        created_at=tool_call.created_at,
    )

    assert messages[-1].metadata == {
        "operation_key": "opaque-image-operation",
        "tool_result_status": "failed",
    }


def test_harness_model_step_repairs_rejected_model_response_once() -> None:
    created_at = datetime(2026, 7, 23, 9, 10, tzinfo=UTC)

    class RejectThenCompleteGateway:
        def __init__(self) -> None:
            self.requests: list[list[SessionMessage]] = []

        def complete(self, messages, *, tools=()):
            raise AssertionError("streaming path expected")

        def complete_stream(self, messages, *, tools=(), on_text_delta):
            self.requests.append(list(messages))
            if len(self.requests) == 1:
                on_text_delta(ModelTextDelta(index=0, content="Preparing report."))
                raise ModelResponseRejectedError(
                    "invalid_tool_arguments_json",
                    phase="tool_arguments",
                    retryable=True,
                    provider_tool_name="files__write",
                    error_position=116,
                )
            on_text_delta(ModelTextDelta(index=0, content="Report ready."))
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Report ready.",
                    created_at=created_at,
                ),
                call_metadata=ModelCallMetadata(provider="deepseek"),
            )

    gateway = RejectThenCompleteGateway()
    events = []
    step = HarnessModelStep(
        available_tools=(RESEARCH_TOOL,),
        event_sink=events.append,
    )
    completion = step.request_completion(
        [
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content="Create the report.",
                created_at=created_at,
            )
        ],
        gateway,
        allow_tools=True,
    )

    assert len(gateway.requests) == 2
    assert gateway.requests[1][-1].role is MessageRole.SYSTEM
    assert gateway.requests[1][-1].metadata["internal_model_response_repair"] is True
    assert completion.call_metadata.retry_count == 0
    assert completion.call_metadata.response_repair_count == 1
    assert completion.call_metadata.normalized_error == "invalid_tool_arguments_json"
    assert [
        event.payload["delta_index"]
        for event in events
        if event.event_type is EventType.MODEL_RESPONSE_DELTA
    ] == [0]
    assert [
        event.payload["content_delta"]
        for event in events
        if event.event_type is EventType.MODEL_RESPONSE_DELTA
    ] == ["Report ready."]

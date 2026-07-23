from datetime import UTC, datetime
from pathlib import Path

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.memories import MemoryType
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.events import EventType
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelTextDelta,
    ModelToolDefinition,
)
from agent_core.harness import HarnessModelStep, HarnessTask
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput
from agent_core.ports.model_gateway import ModelResponseRejectedError


class StaticContextCompiler:
    def build_system_prompt(
        self,
        *,
        task_input: str,
        workspace_root: Path,
        max_tokens: int,
        runtime_evidence: tuple[RuntimeEvidenceInput, ...] = (),
        confirmed_memories: tuple[ConfirmedMemoryInput, ...] = (),
    ) -> str | None:
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

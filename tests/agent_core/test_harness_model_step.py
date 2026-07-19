from datetime import UTC, datetime
from pathlib import Path

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.memories import MemoryType
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.harness import HarnessModelStep, HarnessTask
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput


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

from datetime import UTC, datetime

import pytest
from agent_context import LocalContextCompiler
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelContextWindow, ModelToolDefinition
from agent_core.harness.context_window import ContextWindowExceededError, plan_context_window
from agent_core.harness.model_step import HarnessModelStep

NOW = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)


class _BoundedGateway:
    def __init__(self, window: ModelContextWindow) -> None:
        self.context_window = window
        self.call_count = 0

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        self.call_count += 1
        raise AssertionError("provider must not be called for an over-budget request")


def test_request_completion_hard_gate_prevents_provider_call() -> None:
    gateway = _BoundedGateway(
        ModelContextWindow(
            context_tokens=400,
            max_output_tokens=100,
            compaction_reserve_tokens=50,
            protocol_reserve_tokens=50,
        )
    )

    with pytest.raises(ContextWindowExceededError, match="exceeds input budget"):
        HarnessModelStep().request_completion(
            [_message(MessageRole.USER, "x" * 2_000)],
            gateway,
            allow_tools=False,
        )

    assert gateway.call_count == 0


def test_prepare_conversation_rejects_uncompressible_protected_input() -> None:
    gateway = _BoundedGateway(
        ModelContextWindow(
            context_tokens=500,
            max_output_tokens=100,
            compaction_reserve_tokens=50,
            protocol_reserve_tokens=50,
        )
    )
    messages = [_message(MessageRole.USER, "protected" * 300)]

    with pytest.raises(ContextWindowExceededError, match="exceeds input budget"):
        HarnessModelStep(conversation_compactor=LocalContextCompiler()).prepare_conversation(
            messages,
            gateway,
            allow_tools=False,
            user_goal="Keep the original request.",
            created_at=NOW,
        )

    assert gateway.call_count == 0


def test_context_plan_counts_tool_schema_and_reserves() -> None:
    tool = ModelToolDefinition(
        name="files.read",
        description="Read a file " + "x" * 500,
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    window = ModelContextWindow(
        context_tokens=400,
        max_output_tokens=100,
        compaction_reserve_tokens=50,
        protocol_reserve_tokens=50,
    )

    without_tool = plan_context_window((_message(MessageRole.USER, "read"),), (), window)
    with_tool = plan_context_window((_message(MessageRole.USER, "read"),), (tool,), window)

    assert without_tool.within_budget is True
    assert with_tool.estimated_input_tokens > without_tool.estimated_input_tokens
    assert with_tool.within_budget is False


def _message(role: MessageRole, content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=role,
        content=content,
        created_at=NOW,
    )

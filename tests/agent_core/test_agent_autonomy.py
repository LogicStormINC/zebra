"""Offline check: tools remain available, but direct answers need no tool execution."""

from datetime import UTC, datetime
from unittest.mock import Mock

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.model_step_support import AGENT_EXECUTION_GUIDANCE


def test_direct_answer_with_available_tools_finishes_in_one_request():
    now = datetime.now(UTC)
    model = ScriptedModelGateway(
        (
            ScriptedModelResponse(
                ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="接入完毕",
                        created_at=now,
                    )
                )
            ),
        )
    )
    tools = Mock(spec=["execute"])
    tools.execute.side_effect = AssertionError("direct response must not execute a tool")
    step = HarnessModelStep(
        available_tools=(
            ModelToolDefinition(
                name="sources.list",
                description="List sources",
                parameters={"type": "object", "properties": {}},
            ),
        )
    )
    orchestrator = SingleAttemptOrchestrator(model, Mock(), tools, model_step=step)
    result = HarnessLoop().run(
        HarnessTask(title="Reply", user_input="回复接入完毕"), orchestrator.run, created_at=now
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["model_calls_used"] == 1
    assert result.attempt_result.metadata["tool_calls_executed"] == 0
    assert len(model.requests) == 1 and model.tool_requests[0]
    assert sum(AGENT_EXECUTION_GUIDANCE in m.content for m in model.requests[0]) == 1
    tools.execute.assert_not_called()

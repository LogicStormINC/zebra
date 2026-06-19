from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessTask,
    SingleAttemptOrchestrator,
)


class AllowAllPolicyEngine:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed in smoke test",
            policy_profile="smoke",
        )


class StaticToolGateway:
    def __init__(self, result: ToolResult) -> None:
        self._result = result

    def execute(self, _tool_call: ToolCall) -> ToolResult:
        return self._result


def test_mock_harness_loop_runs_end_to_end() -> None:
    created_at = datetime(2026, 6, 19, 22, 40, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "README.md"},
        created_at=created_at,
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will inspect the README.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                )
            ),
        )
    )
    tool_result = ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="readme contents",
        metadata={"path": "README.md"},
    )
    loop = HarnessLoop()
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        StaticToolGateway(tool_result),
    )

    result = loop.run(
        HarnessTask(
            title="Inspect README",
            user_input="Read the README first.",
            max_attempts=1,
            max_model_calls=1,
            max_tool_calls=1,
        ),
        orchestrator.run,
        created_at=created_at,
    )

    assert result.run_result.final_outcome is HarnessAttemptOutcome.COMPLETED
    assert result.run_result.model_calls_used == 1
    assert result.run_result.tool_calls_used == 1
    assert result.attempt_result.metadata["tool_name"] == "files.read"
    assert gateway.requests[0][0].content == "Read the README first."

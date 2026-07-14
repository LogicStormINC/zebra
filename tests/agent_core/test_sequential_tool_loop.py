from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessModelStep,
    HarnessStopReason,
    HarnessTask,
    SingleAttemptOrchestrator,
)

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
TOOLS = (
    ModelToolDefinition(
        name="files.read",
        description="Read a file.",
        parameters={"type": "object", "properties": {}},
    ),
    ModelToolDefinition(
        name="tests.run",
        description="Run tests.",
        parameters={"type": "object", "properties": {}},
    ),
)


class AllowAllPolicy:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed",
            policy_profile="test",
        )


class SequenceToolGateway:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=f"result:{tool_call.name}",
        )


def test_bounded_loop_executes_two_tools_before_final_answer() -> None:
    first = _tool_call("files.read", {"path": "input.txt"}, "call_read")
    second = _tool_call("tests.run", {"preset": "test"}, "call_test")
    gateway = _gateway(
        _completion("Read the input.", first),
        _completion("Validate the result.", second),
        _completion("The input is valid."),
    )
    tools = SequenceToolGateway()

    result = HarnessLoop().run(
        HarnessTask(
            title="Sequential task",
            user_input="Read and validate the input.",
            max_model_calls=3,
            max_tool_calls=2,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == "The input is valid."
    assert result.run_result.model_calls_used == 3
    assert result.run_result.tool_calls_used == 2
    assert [call.name for call in tools.calls] == ["files.read", "tests.run"]
    assert gateway.tool_requests == (TOOLS, TOOLS, ())
    assert [message.role for message in gateway.requests[2]][-5:] == [
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.USER,
    ]


def test_bounded_loop_blocks_repeated_action_with_new_call_identity() -> None:
    first = _tool_call("files.read", {"path": "same.txt"}, "call_one")
    repeated = _tool_call("files.read", {"path": "same.txt"}, "call_two")
    gateway = _gateway(
        _completion("Read it.", first),
        _completion("Read it again.", repeated),
    )
    tools = SequenceToolGateway()

    result = HarnessLoop().run(
        HarnessTask(
            title="Repeated task",
            user_input="Inspect the file.",
            max_model_calls=4,
            max_tool_calls=3,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == "repeated_tool_call"
    assert result.run_result.model_calls_used == 2
    assert result.run_result.tool_calls_used == 1
    assert len(tools.calls) == 1


def test_bounded_loop_stops_when_no_model_call_remains_for_final_answer() -> None:
    tool_call = _tool_call("files.read", {"path": "input.txt"}, "call_read")
    gateway = _gateway(_completion("Read the input.", tool_call))

    result = HarnessLoop().run(
        HarnessTask(
            title="Exhausted task",
            user_input="Read the input.",
            max_model_calls=1,
            max_tool_calls=1,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            SequenceToolGateway(),
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == ("model_call_budget_exhausted")
    assert result.run_result.stop_reason is HarnessStopReason.MODEL_CALL_BUDGET_EXHAUSTED


def _gateway(*completions: ModelCompletion) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=tuple(ScriptedModelResponse(completion=completion) for completion in completions)
    )


def _completion(content: str, tool_call: ToolCall | None = None) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=NOW,
        ),
        tool_calls=(tool_call,) if tool_call is not None else (),
    )


def _tool_call(name: str, arguments: dict[str, object], call_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
        provider_call_id=call_id,
    )

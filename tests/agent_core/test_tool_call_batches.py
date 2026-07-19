from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
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

NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
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


class PolicyByName:
    def __init__(self, denied_name: str | None = None) -> None:
        self._denied_name = denied_name

    def evaluate_tool_call(self, tool_call: ToolCall) -> PolicyDecision:
        denied = tool_call.name == self._denied_name
        return PolicyDecision(
            decision=PolicyDecisionType.DENY if denied else PolicyDecisionType.ALLOW,
            reason="denied in test" if denied else "allowed in test",
            policy_profile="test",
        )


class RecordingToolGateway:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=f"result:{tool_call.provider_call_id}",
        )


class FailingToolGateway(RecordingToolGateway):
    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED,
            metadata={"reason": "not_a_file", "detail": "missing.txt does not exist"},
        )


def test_provider_batch_executes_all_calls_in_order_before_next_model_request() -> None:
    first = _call("files.read", {"path": "a.txt"}, "call_a")
    second = _call("tests.run", {"preset": "test"}, "call_b")
    gateway = _gateway(
        _completion("Run both operations.", first, second),
        _completion("Both operations completed."),
    )
    tools = RecordingToolGateway()

    result = _run(gateway, tools, max_model_calls=2, max_tool_calls=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.run_result.model_calls_used == 2
    assert result.run_result.tool_calls_used == 2
    assert tools.calls == [first, second]
    second_request = gateway.requests[1]
    assert second_request[-4].tool_calls == (first, second)
    assert [message.role for message in second_request][-4:] == [
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.TOOL,
        MessageRole.USER,
    ]
    assert [message.tool_call_id for message in second_request[-3:-1]] == [
        "call_a",
        "call_b",
    ]


def test_provider_batch_lets_model_recover_from_failed_tool() -> None:
    failed = _call("files.read", {"path": "missing.txt"}, "call_missing")
    gateway = _gateway(
        _completion("Read the file.", failed),
        _completion("Recovered from the available context."),
    )
    tools = FailingToolGateway()

    result = _run(gateway, tools, max_model_calls=2, max_tool_calls=1)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.run_result.model_calls_used == 2
    assert tools.calls == [failed]
    assert gateway.requests[1][-2].content == (
        '{"detail": "missing.txt does not exist", "reason": "not_a_file", '
        '"status": "failed"}'
    )
    assert any(event.event_type is EventType.TOOL_EXECUTION_FAILED for event in result.events)


def test_provider_batch_stops_before_repeated_member_and_leaves_tail_unexecuted() -> None:
    first = _call("files.read", {"path": "same.txt"}, "call_a")
    repeated = _call("files.read", {"path": "same.txt"}, "call_b")
    tail = _call("tests.run", {"preset": "test"}, "call_c")
    gateway = _gateway(_completion("Repeat then test.", first, repeated, tail))
    tools = RecordingToolGateway()

    result = _run(gateway, tools, max_model_calls=3, max_tool_calls=3)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == "repeated_tool_call"
    assert result.attempt_result.metadata["remaining_tool_call_count"] == 2
    assert tools.calls == [first]


def test_provider_batch_stops_explicitly_when_tool_budget_is_exhausted() -> None:
    calls = (
        _call("files.read", {"path": "a.txt"}, "call_a"),
        _call("files.read", {"path": "b.txt"}, "call_b"),
        _call("tests.run", {"preset": "test"}, "call_c"),
    )
    gateway = _gateway(_completion("Run the batch.", *calls))
    tools = RecordingToolGateway()

    result = _run(gateway, tools, max_model_calls=3, max_tool_calls=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == ("tool_call_budget_exhausted")
    assert result.run_result.stop_reason is HarnessStopReason.TOOL_CALL_BUDGET_EXHAUSTED
    assert tools.calls == list(calls[:2])
    assert sum(event.event_type is EventType.TOOL_CALL_PROPOSED for event in result.events) == 2


def test_provider_batch_denial_stops_before_denied_member_and_tail() -> None:
    first = _call("files.read", {"path": "a.txt"}, "call_a")
    denied = _call("tests.run", {"preset": "test"}, "call_b")
    tail = _call("files.read", {"path": "b.txt"}, "call_c")
    gateway = _gateway(_completion("Run the batch.", first, denied, tail))
    tools = RecordingToolGateway()

    result = _run(
        gateway,
        tools,
        max_model_calls=3,
        max_tool_calls=3,
        policy=PolicyByName("tests.run"),
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["policy_decision"] == "deny"
    assert tools.calls == [first]
    assert sum(event.event_type is EventType.POLICY_DECISION_MADE for event in result.events) == 2


def _run(
    gateway: ScriptedModelGateway,
    tools: RecordingToolGateway,
    *,
    max_model_calls: int,
    max_tool_calls: int,
    policy: PolicyByName | None = None,
):
    return HarnessLoop().run(
        HarnessTask(
            title="Batch task",
            user_input="Complete the batch.",
            max_model_calls=max_model_calls,
            max_tool_calls=max_tool_calls,
        ),
        SingleAttemptOrchestrator(
            gateway,
            policy or PolicyByName(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )


def _gateway(*completions: ModelCompletion) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=tuple(ScriptedModelResponse(completion=completion) for completion in completions)
    )


def _completion(content: str, *tool_calls: ToolCall) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=NOW,
        ),
        tool_calls=tool_calls,
    )


def _call(name: str, arguments: dict[str, object], provider_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
        provider_call_id=provider_id,
    )

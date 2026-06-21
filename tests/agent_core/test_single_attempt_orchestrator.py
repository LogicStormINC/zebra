from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    FirstToolCallSelectionStrategy,
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessTask,
    SingleAttemptOrchestrator,
)


class AllowAllPolicyEngine:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed in test",
            policy_profile="test",
        )


class StaticToolGateway:
    def __init__(self, result: ToolResult) -> None:
        self._result = result
        self.executed_tool_call: ToolCall | None = None

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.executed_tool_call = tool_call
        return self._result


def test_single_attempt_orchestrator_runs_model_to_tool_success_path() -> None:
    created_at = datetime(2026, 6, 19, 22, 0, tzinfo=UTC)
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
                    call_metadata=ModelCallMetadata(
                        provider="openai",
                        model_name="gpt-5-codex",
                        latency_ms=850,
                        cache_hit=False,
                        cost_usd=0.024,
                        usage=ModelUsage(
                            input_tokens=120,
                            output_tokens=36,
                            total_tokens=156,
                        ),
                    ),
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
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        StaticToolGateway(tool_result),
    )
    loop = HarnessLoop()

    result = loop.run(
        HarnessTask(title="Inspect README", user_input="Read the README first."),
        orchestrator.run,
        created_at=created_at,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.session.status.value == "completed"
    assert result.attempt_result.metadata["tool_status"] == "executed"
    assert result.events[4].payload["provider"] == "openai"
    assert result.events[4].payload["model_name"] == "gpt-5-codex"
    assert result.events[4].payload["total_tokens"] == 156
    assert [event.event_type for event in result.events] == [
        EventType.SESSION_CREATED,
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TASK_PREPARED,
        EventType.HARNESS_ATTEMPT_STARTED,
        EventType.MODEL_RESPONSE_RECEIVED,
        EventType.PLAN_PROPOSED,
        EventType.TOOL_CALL_PROPOSED,
        EventType.POLICY_DECISION_MADE,
        EventType.TOOL_EXECUTION_STARTED,
        EventType.TOOL_EXECUTION_COMPLETED,
        EventType.TESTS_COMPLETED,
        EventType.SESSION_COMPLETED,
    ]


def test_single_attempt_orchestrator_marks_failed_tool_execution() -> None:
    created_at = datetime(2026, 6, 19, 22, 5, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="tests.run",
        arguments={"preset": "smoke"},
        created_at=created_at,
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will run the smoke checks.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                )
            ),
        )
    )
    tool_result = ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        output="",
        metadata={"stderr": "failure"},
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        StaticToolGateway(tool_result),
    )
    loop = HarnessLoop()

    result = loop.run(
        HarnessTask(title="Run smoke", user_input="Run smoke checks."),
        orchestrator.run,
        created_at=created_at,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.session.status.value == "failed"
    assert result.attempt_result.metadata["tool_status"] == "failed"
    assert result.events[-3].event_type is EventType.TOOL_EXECUTION_FAILED
    assert result.events[-2].event_type is EventType.TESTS_COMPLETED
    assert result.events[-1].event_type is EventType.SESSION_FAILED


def test_first_tool_call_selection_strategy_is_deterministic() -> None:
    created_at = datetime(2026, 6, 19, 22, 10, tzinfo=UTC)
    first_tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "README.md"},
        created_at=created_at,
    )
    second_tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="tests.run",
        arguments={"preset": "smoke"},
        created_at=created_at,
    )

    selection = FirstToolCallSelectionStrategy().select(
        (first_tool_call, second_tool_call)
    )

    assert selection.tool_call == first_tool_call
    assert selection.summary == "selected first tool call"
    assert selection.metadata == {
        "selected_index": 0,
        "candidate_count": 2,
    }


def test_single_attempt_orchestrator_uses_selected_tool_call_from_multi_tool_completion() -> None:
    created_at = datetime(2026, 6, 19, 22, 15, tzinfo=UTC)
    first_tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "README.md"},
        created_at=created_at,
    )
    second_tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="tests.run",
        arguments={"preset": "smoke"},
        created_at=created_at,
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will inspect the README before running checks.",
                        created_at=created_at,
                    ),
                    tool_calls=(first_tool_call, second_tool_call),
                )
            ),
        )
    )
    tool_result = ToolResult(
        tool_call_id=first_tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="readme contents",
        metadata={"path": "README.md"},
    )
    tool_gateway = StaticToolGateway(tool_result)
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        tool_gateway,
    )
    loop = HarnessLoop()

    result = loop.run(
        HarnessTask(title="Inspect README", user_input="Read before running checks."),
        orchestrator.run,
        created_at=created_at,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tool_gateway.executed_tool_call == first_tool_call
    assert result.attempt_result.metadata["tool_name"] == "files.read"
    assert result.attempt_result.metadata["tool_selection_summary"] == (
        "selected first tool call"
    )
    assert result.attempt_result.metadata["tool_selection_metadata"] == {
        "selected_index": 0,
        "candidate_count": 2,
    }
    assert result.events[6].payload["tool_name"] == "files.read"
    assert result.events[6].payload["selection_summary"] == "selected first tool call"
    assert result.events[6].payload["selection_metadata"] == {
        "selected_index": 0,
        "candidate_count": 2,
    }

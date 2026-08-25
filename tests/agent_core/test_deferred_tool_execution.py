"""Deferred tool execution: scheduled client effects suspend the attempt."""

from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.sessions import Session
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessContext,
    HarnessLoop,
    HarnessStopReason,
    HarnessTask,
    SingleAttemptOrchestrator,
)

CREATED_AT = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
EFFECT_ID = "0e4a6f8c-1111-4222-8333-444455556666"


class AllowAllPolicyEngine:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed in test",
            policy_profile="test",
        )


class DeferredClientGateway:
    """Returns a deferred marker instead of a terminal tool result."""

    def __init__(self, tool_call_id, action_name: str) -> None:
        self._tool_call_id = tool_call_id
        self._action_name = action_name
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=self._tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="",
            metadata={
                "client_effect_deferred": True,
                "client_effect_id": EFFECT_ID,
                "action_name": self._action_name,
                "client_effect_idempotency_key": "client-effect:1:run-1:x",
            },
        )


class ImmediateGateway:
    def __init__(self, tool_call_id) -> None:
        self._tool_call_id = tool_call_id

    def execute(self, tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=self._tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="immediate result",
            metadata={},
        )


def _completion_with_call(tool_call: ToolCall) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="Opening the timeline.",
            created_at=CREATED_AT,
        ),
        tool_calls=(tool_call,),
        call_metadata=ModelCallMetadata(
            provider="openai",
            model_name="gpt-5-codex",
            latency_ms=800,
            cache_hit=False,
            cost_usd=0.01,
            usage=ModelUsage(input_tokens=50, output_tokens=12, total_tokens=62),
        ),
    )


def _final_completion() -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="Timeline opened; analysis complete.",
            created_at=CREATED_AT,
        ),
        tool_calls=(),
        call_metadata=ModelCallMetadata(
            provider="openai",
            model_name="gpt-5-codex",
            latency_ms=500,
            cache_hit=False,
            cost_usd=0.005,
            usage=ModelUsage(input_tokens=80, output_tokens=20, total_tokens=100),
        ),
    )


def test_deferred_client_effect_suspends_without_a_terminal_tool_event() -> None:
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="trench.ui.timeline.open",
        arguments={"entityId": "ent-9"},
        created_at=CREATED_AT,
    )
    gateway = DeferredClientGateway(tool_call.tool_call_id, "trench.ui.timeline.open")
    orchestrator = SingleAttemptOrchestrator(
        ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=_completion_with_call(tool_call)
                ),
            )
        ),
        AllowAllPolicyEngine(),
        gateway,
    )

    result = HarnessLoop().run(
        HarnessTask(title="Open timeline", user_input="Open the entity timeline."),
        orchestrator.run,
        created_at=CREATED_AT,
    )

    attempt = result.attempt_result
    assert attempt.outcome is HarnessAttemptOutcome.WAITING_EXTERNAL_TOOL
    assert attempt.metadata["stop_reason"] == "waiting_client_effect"
    assert attempt.metadata["client_effect_ids"] == [EFFECT_ID]
    assert result.run_result.stop_reason is HarnessStopReason.CLIENT_EFFECT_REQUIRED
    event_types = [event.event_type for event in result.events]
    assert EventType.CLIENT_EFFECT_SCHEDULED in event_types
    assert EventType.TOOL_EXECUTION_COMPLETED not in event_types
    assert EventType.SESSION_FAILED not in event_types
    assert EventType.SESSION_COMPLETED not in event_types


def test_immediate_tool_behavior_is_unchanged() -> None:
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "README.md"},
        created_at=CREATED_AT,
    )
    orchestrator = SingleAttemptOrchestrator(
        ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(completion=_completion_with_call(tool_call)),
                ScriptedModelResponse(completion=_final_completion()),
            )
        ),
        AllowAllPolicyEngine(),
        ImmediateGateway(tool_call.tool_call_id),
    )

    result = HarnessLoop().run(
        HarnessTask(title="Read file", user_input="Read the README."),
        orchestrator.run,
        created_at=CREATED_AT,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    event_types = [event.event_type for event in result.events]
    assert EventType.TOOL_EXECUTION_COMPLETED in event_types
    assert EventType.CLIENT_EFFECT_SCHEDULED not in event_types


def test_receipt_resumes_the_original_tool_call() -> None:
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="trench.ui.timeline.open",
        arguments={"entityId": "ent-9"},
        created_at=CREATED_AT,
    )
    deferred_completion = _completion_with_call(tool_call)
    events: list = []
    context = HarnessContext(
        task=HarnessTask(title="Open timeline", user_input="Open the entity timeline."),
        session=Session.create(title="resume", created_at=CREATED_AT),
        attempt=HarnessAttempt(number=1, started_at=CREATED_AT),
    )
    orchestrator_with_sink = SingleAttemptOrchestrator(
        ScriptedModelGateway(
            responses=(ScriptedModelResponse(completion=_final_completion()),)
        ),
        AllowAllPolicyEngine(),
        DeferredClientGateway(tool_call.tool_call_id, "trench.ui.timeline.open"),
        event_sink=events.append,
    )

    resumed = orchestrator_with_sink.continue_completed_tool(
        context,
        completion=deferred_completion,
        tool_call=tool_call,
        tool_result=ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="timeline opened for ent-9",
            metadata={"client_effect_id": EFFECT_ID},
        ),
        conversation=(),
        model_calls_used=1,
        tool_calls_executed=0,
        assistant_message="Opening the timeline.",
    )

    assert resumed.outcome is HarnessAttemptOutcome.COMPLETED

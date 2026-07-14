from datetime import UTC, datetime

from agent_context import SUMMARY_MARKER, LocalContextCompiler, estimate_message_tokens
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessContext,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
TOOLS = tuple(
    ModelToolDefinition(
        name=name,
        description=f"Execute {name}.",
        parameters={"type": "object", "properties": {}},
    )
    for name in ("files.read", "command.run")
)


class ApprovalPolicy:
    def evaluate_tool_call(self, tool_call: ToolCall) -> PolicyDecision:
        approval = tool_call.name == "command.run"
        return PolicyDecision(
            decision=(
                PolicyDecisionType.REQUIRE_APPROVAL if approval else PolicyDecisionType.ALLOW
            ),
            reason="approval required" if approval else "allowed",
            policy_profile="test",
        )


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        output = "OLD-SECRET-" * 300 if len(self.calls) == 1 else f"ok:{tool_call.name}"
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=output,
        )


def test_compacted_conversation_survives_exact_approval_continuation() -> None:
    first = _call("files.read", {"path": "old.txt"}, "call_old")
    second = _call("files.read", {"path": "latest.txt"}, "call_latest")
    pending = _call("command.run", {"command": ["echo", "ok"]}, "call_pending")
    gateway = ScriptedModelGateway(
        responses=tuple(
            ScriptedModelResponse(completion=completion)
            for completion in (
                _completion("Read old.", first),
                _completion("Read latest.", second),
                _completion("Run command.", pending),
                _completion("Finished from compacted evidence."),
            )
        )
    )
    tools = RecordingTools()
    compiler = LocalContextCompiler()
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        ApprovalPolicy(),
        tools,
        model_step=HarnessModelStep(
            available_tools=TOOLS,
            conversation_compactor=compiler,
            conversation_token_budget=180,
        ),
        synthesize_tool_results=True,
    )
    task = HarnessTask(
        title="Compacted approval",
        user_input="Read two inputs, then run the command.",
        max_model_calls=4,
        max_tool_calls=3,
    )
    waiting = HarnessLoop().run(task, orchestrator.run, created_at=NOW)

    assert waiting.attempt_result.outcome is HarnessAttemptOutcome.WAITING_APPROVAL
    compacted = next(
        event for event in waiting.events if event.event_type is EventType.CONTEXT_COMPACTED
    )
    assert compacted.payload["after_tokens"] <= 180
    assert "OLD-SECRET" not in str(compacted.payload)
    approval = next(
        event for event in waiting.events if event.event_type is EventType.APPROVAL_REQUESTED
    )
    conversation = tuple(
        SessionMessage.model_validate(message) for message in approval.payload["conversation"]
    )
    assert any(SUMMARY_MARKER in message.content for message in conversation)
    assert estimate_message_tokens(conversation[:-1]) <= 180
    assert conversation[-1].tool_calls == (pending,)

    completed = orchestrator.continue_approved_tool_call(
        HarnessContext(
            task=task,
            session=waiting.session,
            attempt=HarnessAttempt(number=1, started_at=NOW),
        ),
        initial_completion=_completion("Run command.", pending),
        tool_call=pending,
        conversation=conversation,
        model_calls_used=3,
        tool_calls_executed=2,
    )

    assert completed.outcome is HarnessAttemptOutcome.COMPLETED
    assert completed.metadata["assistant_message"] == "Finished from compacted evidence."
    assert tools.calls == [first, second, pending]


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


def _call(name: str, arguments: dict[str, object], provider_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
        provider_call_id=provider_id,
    )

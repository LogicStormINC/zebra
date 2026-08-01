from dataclasses import replace
from datetime import UTC, datetime

import pytest
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import (
    new_artifact_id,
    new_event_id,
    new_message_id,
    new_tool_call_id,
)
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_media import (
    ModelInputModality,
    ModelMediaCapabilities,
    ModelMediaInput,
    model_media_source_event_ids,
)
from agent_core.domain.modeling import ModelCompletion, ModelContextWindow, ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.context_window import ContextWindowExceededError
from agent_core.ports.conversation_compactor import ConversationCompactionResult

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
MEDIA = ModelMediaInput(
    artifact_id=new_artifact_id(),
    media_type="image/png",
    sha256="0" * 64,
    size_bytes=1,
    display_name="chart.png",
    ordinal=0,
    source_message_id=new_event_id(),
)
READ_TOOL = ModelToolDefinition(
    name="files.read",
    description="Read one file.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
)


def test_media_replays_after_tool_and_compaction_without_bypassing_policy_or_audit() -> None:
    tool_call = _tool_call("call-read")
    gateway = _MediaGateway(
        _completion("Read the evidence.", tool_call),
        _completion("The image and tool output agree."),
    )
    events = []

    result = HarnessLoop().run(
        HarnessTask(
            title="Native media",
            user_input="Compare the chart with the file.",
            max_model_calls=2,
            max_tool_calls=1,
            media_inputs=(MEDIA,),
        ),
        SingleAttemptOrchestrator(
            gateway,
            _AllowPolicy(),
            _ToolGateway(),
            model_step=HarnessModelStep(
                available_tools=(READ_TOOL,),
                conversation_compactor=_AlwaysCompact(),
                event_sink=events.append,
            ),
            synthesize_tool_results=True,
            event_sink=events.append,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert gateway.media_requests == [(MEDIA,), (MEDIA,)]
    assert gateway.tool_requests == [(READ_TOOL,), ()]
    assert any(event.event_type is EventType.POLICY_DECISION_MADE for event in events)
    assert any(event.event_type is EventType.TOOL_EXECUTION_COMPLETED for event in events)
    assert any(event.event_type is EventType.CONTEXT_COMPACTED for event in events)


def test_harness_semantic_user_message_declares_exact_media_source_events() -> None:
    second_source_event_id = new_event_id()
    second_media = replace(
        MEDIA,
        artifact_id=new_artifact_id(),
        ordinal=1,
        source_message_id=second_source_event_id,
    )

    messages = HarnessModelStep().build_initial_messages(
        HarnessTask(
            title="Native media sources",
            user_input="Review the current task images.",
            media_inputs=(MEDIA, second_media),
        ),
        created_at=NOW,
    )

    [user_message] = [message for message in messages if message.role is MessageRole.USER]
    assert model_media_source_event_ids(user_message.metadata) == (
        MEDIA.source_message_id,
        second_source_event_id,
    )


def test_media_replays_for_tool_loop_terminal_synthesis() -> None:
    calls = tuple(_tool_call(f"call-{index}", query=f"variant-{index}") for index in range(4))
    gateway = _MediaGateway(
        *(_completion("Collect more.", call) for call in calls),
        _completion("Synthesized from the available evidence."),
    )

    result = HarnessLoop().run(
        HarnessTask(
            title="Native media synthesis",
            user_input="Use the chart evidence.",
            media_inputs=(MEDIA,),
        ),
        SingleAttemptOrchestrator(
            gateway,
            _AllowPolicy(),
            _StableToolGateway(),
            model_step=HarnessModelStep(available_tools=(READ_TOOL,)),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.metadata["terminal_synthesis_attempted"] is True
    assert gateway.media_requests == [(MEDIA,)] * 5
    assert gateway.tool_requests[-1] == ()


def test_media_token_estimate_is_part_of_the_hard_gate() -> None:
    gateway = _MediaGateway(
        _completion("unreachable"),
        context_window=ModelContextWindow(
            context_tokens=300,
            max_output_tokens=100,
            compaction_reserve_tokens=50,
            protocol_reserve_tokens=50,
        ),
        media_tokens=200,
    )

    with pytest.raises(ContextWindowExceededError, match="exceeds input budget"):
        HarnessModelStep().request_completion(
            [_user_message("Describe the chart.")],
            gateway,
            allow_tools=False,
            media_inputs=(MEDIA,),
        )

    assert gateway.media_requests == []


def test_harness_loop_preserves_optional_initial_user_event_id_compatibility() -> None:
    assigned_event_id = new_event_id()
    assigned = HarnessLoop().run(
        HarnessTask(title="Assigned event", user_input="Describe the image."),
        SingleAttemptOrchestrator(
            _MediaGateway(_completion("Done.")),
            _AllowPolicy(),
            _ToolGateway(),
            model_step=HarnessModelStep(),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
        initial_user_event_id=assigned_event_id,
    )
    generated = HarnessLoop().run(
        HarnessTask(title="Generated event", user_input="Describe the image."),
        SingleAttemptOrchestrator(
            _MediaGateway(_completion("Done.")),
            _AllowPolicy(),
            _ToolGateway(),
            model_step=HarnessModelStep(),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assigned_user_event = next(
        event for event in assigned.events if event.event_type is EventType.USER_MESSAGE_RECEIVED
    )
    generated_user_event = next(
        event for event in generated.events if event.event_type is EventType.USER_MESSAGE_RECEIVED
    )
    assert assigned_user_event.event_id == assigned_event_id
    assert generated_user_event.event_id != assigned_event_id
    assert [event.event_type for event in assigned.events] == [
        event.event_type for event in generated.events
    ]


class _MediaGateway:
    media_capabilities = ModelMediaCapabilities(
        input_modalities=frozenset({ModelInputModality.TEXT, ModelInputModality.IMAGE}),
        supports_tools_with_media=True,
        supports_streaming_with_media=True,
        max_image_count=4,
        max_image_bytes=5 * 1024 * 1024,
        max_total_image_bytes=20 * 1024 * 1024,
        image_media_types=frozenset({"image/png"}),
    )

    def __init__(
        self,
        *responses: ModelCompletion,
        context_window: ModelContextWindow | None = None,
        media_tokens: int = 1,
    ) -> None:
        self._responses = responses
        self._cursor = 0
        self.context_window = context_window or ModelContextWindow()
        self._media_tokens = media_tokens
        self.media_requests: list[tuple[ModelMediaInput, ...]] = []
        self.tool_requests: list[tuple[ModelToolDefinition, ...]] = []

    def estimate_media_tokens(self, media_inputs: tuple[ModelMediaInput, ...]) -> int:
        assert media_inputs == (MEDIA,)
        return self._media_tokens

    def complete(
        self,
        _messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
        media_inputs: tuple[ModelMediaInput, ...] = (),
    ) -> ModelCompletion:
        self.media_requests.append(media_inputs)
        self.tool_requests.append(tools)
        response = self._responses[self._cursor]
        self._cursor += 1
        return response


class _AllowPolicy:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed",
            policy_profile="test",
        )


class _ToolGateway:
    def execute(self, tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="chart evidence",
        )


class _StableToolGateway(_ToolGateway):
    def execute(self, tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="same evidence",
        )


class _AlwaysCompact:
    def compact_conversation(self, messages, *, user_goal, max_tokens, created_at):
        return ConversationCompactionResult(
            messages=tuple(messages),
            before_tokens=10,
            after_tokens=10,
            removed_message_count=0,
            retained_message_count=len(messages),
            compacted=True,
            within_budget=True,
            provenance="test-media-compaction",
            capsule=ContextCapsule(
                capsule_id="ctxcap-media",
                objective=user_goal,
                immediate_next="continue",
                source_hash="a" * 64,
                confidence=1.0,
                created_at=created_at,
            ),
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


def _tool_call(call_id: str, *, query: str = "chart") -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "evidence.txt", "query": query},
        created_at=NOW,
        provider_call_id=call_id,
    )


def _user_message(content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content=content,
        created_at=NOW,
    )

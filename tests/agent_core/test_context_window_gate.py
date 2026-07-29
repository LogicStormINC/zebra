from datetime import UTC, datetime

import pytest
from agent_context import LocalContextCompiler
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_continuation import (
    ProviderContinuationCapability,
    ProviderContinuationMode,
    ProviderContinuationRef,
)
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelContextWindow,
    ModelToolDefinition,
    ModelUsage,
)
from agent_core.harness.context_window import ContextWindowExceededError, plan_context_window
from agent_core.harness.model_step import HarnessModelStep
from agent_core.ports.conversation_compactor import ConversationCompactionResult

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


class _CountingGateway:
    context_window = ModelContextWindow(
        profile_name="counted-model",
        context_tokens=1_000,
        max_output_tokens=100,
        compaction_reserve_tokens=50,
        protocol_reserve_tokens=50,
        compaction_trigger_reserve_tokens=50,
    )

    def count_input_tokens(
        self,
        messages: tuple[SessionMessage, ...],
        tools: tuple[ModelToolDefinition, ...],
    ) -> int:
        return 123

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        return ModelCompletion(
            assistant_message=_message(MessageRole.ASSISTANT, "done"),
            call_metadata=ModelCallMetadata(usage=ModelUsage(input_tokens=125)),
        )


class _NativeContinuationGateway(_CountingGateway):
    continuation_capability = ProviderContinuationCapability(
        mode=ProviderContinuationMode.OPAQUE_REFERENCE
    )

    def __init__(self) -> None:
        self.native_calls = 0

    def compact_to_reference(self, capsule: ContextCapsule) -> ProviderContinuationRef:
        return ProviderContinuationRef(
            reference_id="native-1",
            provider="test",
            model_name="counted-model",
            source_hash=capsule.source_hash,
        )

    def complete_from_reference(
        self,
        reference: ProviderContinuationRef,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        self.native_calls += 1
        assert reference.reference_id == "native-1"
        return super().complete(messages, tools=tools)


class _AlwaysCompact:
    def compact_conversation(self, messages, *, user_goal, max_tokens, created_at):
        capsule = ContextCapsule(
            capsule_id="ctxcap-native",
            objective=user_goal,
            immediate_next="continue",
            source_hash="a" * 64,
            confidence=1.0,
            created_at=created_at,
        )
        return ConversationCompactionResult(
            messages=messages,
            before_tokens=20,
            after_tokens=10,
            removed_message_count=1,
            retained_message_count=len(messages),
            compacted=True,
            within_budget=True,
            provenance="test-compaction",
            capsule=capsule,
        )


class _StrictRetryCompactor:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[SessionMessage, ...], int]] = []

    def compact_conversation(self, messages, *, user_goal, max_tokens, created_at):
        original = tuple(messages)
        self.calls.append((original, max_tokens))
        compacted_messages = (
            original
            if len(self.calls) == 1
            else (_message(MessageRole.USER, "strict compacted context"),)
        )
        return ConversationCompactionResult(
            messages=compacted_messages,
            before_tokens=600,
            after_tokens=600 if len(self.calls) == 1 else 20,
            removed_message_count=0 if len(self.calls) == 1 else len(original) - 1,
            retained_message_count=len(compacted_messages),
            compacted=len(self.calls) > 1,
            within_budget=len(self.calls) > 1,
            provenance=f"retry-{len(self.calls)}",
        )


def test_request_completion_hard_gate_prevents_provider_call() -> None:
    gateway = _BoundedGateway(
        ModelContextWindow(
            context_tokens=400,
            max_output_tokens=100,
            compaction_reserve_tokens=50,
            protocol_reserve_tokens=50,
            compaction_trigger_reserve_tokens=50,
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


def test_prepare_conversation_retries_once_from_original_history() -> None:
    gateway = _BoundedGateway(
        ModelContextWindow(
            context_tokens=500,
            max_output_tokens=100,
            compaction_reserve_tokens=50,
            protocol_reserve_tokens=50,
            compaction_trigger_reserve_tokens=50,
        )
    )
    original = [_message(MessageRole.USER, "x" * 2_000)]
    messages = list(original)
    compactor = _StrictRetryCompactor()

    result = HarnessModelStep(conversation_compactor=compactor).prepare_conversation(
        messages,
        gateway,
        allow_tools=False,
        user_goal="Keep the original request.",
        created_at=NOW,
    )

    assert result is not None
    assert len(compactor.calls) == 2
    assert compactor.calls[0][0] == tuple(original)
    assert compactor.calls[1][0] == tuple(original)
    assert compactor.calls[1][1] < compactor.calls[0][1]
    assert messages == list(result.messages)
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


def test_provider_token_counter_and_profile_are_attached_to_completion() -> None:
    completion = HarnessModelStep().request_completion(
        [_message(MessageRole.USER, "count this")],
        _CountingGateway(),
        allow_tools=False,
    )

    assert completion.call_metadata.estimated_input_tokens == 123
    assert completion.call_metadata.input_token_limit == 800
    assert completion.call_metadata.token_estimate_method == "provider"


def test_context_error_exposes_typed_diagnostics() -> None:
    gateway = _BoundedGateway(
        ModelContextWindow(
            profile_name="tiny",
            context_tokens=400,
            max_output_tokens=100,
            compaction_reserve_tokens=50,
            protocol_reserve_tokens=50,
        )
    )

    with pytest.raises(ContextWindowExceededError) as captured:
        HarnessModelStep().request_completion(
            [_message(MessageRole.USER, "x" * 2_000)], gateway, allow_tools=False
        )

    assert captured.value.plan.profile_name == "tiny"
    assert captured.value.plan.within_budget is False
    assert captured.value.plan.token_breakdown["messages"] > 0


def test_compaction_uses_provider_continuation_then_keeps_capsule_fallback() -> None:
    gateway = _NativeContinuationGateway()
    messages = [_message(MessageRole.USER, "continue")]
    step = HarnessModelStep(conversation_compactor=_AlwaysCompact())

    result = step.prepare_conversation(
        messages,
        gateway,
        allow_tools=False,
        user_goal="continue",
        created_at=NOW,
    )
    assert result is not None
    step.prepare_provider_continuation(gateway, result)
    completion = step.request_completion(messages, gateway, allow_tools=False)

    assert result.capsule is not None
    assert gateway.native_calls == 1
    assert completion.assistant_message.content == "done"


def _message(role: MessageRole, content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=role,
        content=content,
        created_at=NOW,
    )

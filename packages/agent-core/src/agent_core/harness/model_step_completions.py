"""High-level completion request builders for HarnessModelStep (Wave 5)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.model_media import ModelMediaInput
from agent_core.domain.modeling import ModelTextDelta
from agent_core.harness.context_recovery import (
    merge_recovery_messages,
    prepare_bounded_conversation,
)
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.provider_continuation import (
    PreparedProviderContinuation,
    continuation_event,
)
from agent_core.ports.conversation_compactor import ConversationCompactionResult
from agent_core.ports.model_gateway import ModelGatewayPort

if TYPE_CHECKING:
    from agent_core.harness.model_step import HarnessModelStep


def prepare_conversation(
    model_step: HarnessModelStep,
    messages: list[SessionMessage],
    model_gateway: ModelGatewayPort,
    *,
    allow_tools: bool,
    user_goal: str,
    created_at: datetime,
    media_inputs: tuple[ModelMediaInput, ...] = (),
) -> ConversationCompactionResult | None:
    result = prepare_bounded_conversation(
        messages,
        model_gateway,
        allow_tools=allow_tools,
        available_tools=model_step._available_tools,
        conversation_compactor=model_step._conversation_compactor,
        conversation_token_budget=model_step._conversation_token_budget,
        compaction_hook=model_step._compaction_hook,
        user_goal=user_goal,
        created_at=created_at,
        media_inputs=media_inputs,
    )
    if result is not None and result.recovery_messages is not None:
        recovery = merge_recovery_messages(
            model_step._recovery_messages,
            result.recovery_messages,
            model_gateway,
            media_inputs=media_inputs,
        )
        if recovery is not None:
            model_step._recovery_messages = recovery
    return result


def recover_conversation(
    model_step: HarnessModelStep,
    messages: list[SessionMessage],
    model_gateway: ModelGatewayPort,
    *,
    media_inputs: tuple[ModelMediaInput, ...] = (),
) -> bool:
    recovery = merge_recovery_messages(
        model_step._recovery_messages,
        tuple(messages),
        model_gateway,
        media_inputs=media_inputs,
    )
    if recovery is None:
        return False
    model_step._recovery_messages = recovery
    model_step._provider_continuation = None
    messages[:] = model_step._recovery_messages
    return True


def _emit_continuation_selection(
    model_step: HarnessModelStep, selection: PreparedProviderContinuation
) -> None:
    if model_step._event_sink is None:
        return
    model_step._event_sink(continuation_event(selection, attempt_number=model_step._attempt_number))


def _emit_text_delta(
    model_step: HarnessModelStep,
    model_call_id: str,
    delta: ModelTextDelta,
) -> None:
    if model_step._event_sink is None:
        return
    model_step._event_sink(
        HarnessEventDraft(
            event_type=EventType.MODEL_RESPONSE_DELTA,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": model_step._attempt_number,
                "model_call_id": model_call_id,
                "delta_index": delta.index,
                "content_delta": delta.content,
            },
        )
    )

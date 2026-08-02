from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import (
    MessageRole,
    SessionMessage,
    without_superseded_operation_failures,
)
from agent_core.domain.model_media import ModelMediaInput
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.harness.context_window import ContextWindowExceededError
from agent_core.harness.hooks import CompactionHook
from agent_core.harness.model_request import build_context_plan, context_window
from agent_core.harness.models import HarnessContext, HarnessEventDraft
from agent_core.harness.orchestration_events import context_compacted_event
from agent_core.ports.conversation_compactor import (
    ConversationCompactionResult,
    ConversationCompactorPort,
)
from agent_core.ports.model_gateway import ModelGatewayPort

if TYPE_CHECKING:
    from agent_core.harness.model_step import HarnessModelStep


def merge_recovery_messages(
    recovery_messages: tuple[SessionMessage, ...],
    messages: tuple[SessionMessage, ...],
    model_gateway: ModelGatewayPort,
    *,
    media_inputs: tuple[ModelMediaInput, ...] = (),
) -> tuple[SessionMessage, ...] | None:
    known = {str(message.message_id) for message in recovery_messages}
    candidate = without_superseded_operation_failures(
        recovery_messages
        + tuple(message for message in messages if str(message.message_id) not in known)
    )
    if not candidate or not build_context_plan(
        candidate,
        (),
        context_window(model_gateway),
        model_gateway,
        media_inputs=media_inputs,
    ).within_budget:
        return None
    return candidate


def append_final_answer_instruction(
    messages: list[SessionMessage],
    *,
    created_at: datetime,
) -> None:
    messages.append(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content=(
                "The tool budget is complete. Answer the original request using "
                "the available tool results. Your final answer must be complete and "
                "self-contained, directly answer the original request, and not merely "
                "say that the work is done or submitted or refer to earlier output. "
                "Truthfully report visible tool results by distinguishing succeeded and "
                "failed results; never claim a failed or missing operation succeeded. "
                "Do not request or invoke another tool."
            ),
            created_at=created_at,
        )
    )


def append_validator_correction_instruction(
    messages: list[SessionMessage],
    *,
    created_at: datetime,
) -> None:
    messages.append(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.SYSTEM,
            content=(
                "A structured validator rejected the candidate. Correct the answer using "
                "the validator result already in this conversation. This is the one bounded "
                "correction pass; do not request or invoke another tool."
            ),
            created_at=created_at,
            metadata={"validator_correction": True},
        )
    )


def prepare_terminal_conversation(
    messages: list[SessionMessage],
    model_gateway: ModelGatewayPort,
    model_step: HarnessModelStep,
    user_goal: str,
    created_at: datetime,
    *,
    media_inputs: tuple[ModelMediaInput, ...] = (),
) -> ConversationCompactionResult | None:
    compaction = model_step.prepare_conversation(
        messages,
        model_gateway,
        allow_tools=False,
        user_goal=user_goal,
        created_at=created_at,
        **({"media_inputs": media_inputs} if media_inputs else {}),
    )
    model_step.recover_conversation(
        messages,
        model_gateway,
        **({"media_inputs": media_inputs} if media_inputs else {}),
    )
    append_final_answer_instruction(messages, created_at=created_at)
    if build_context_plan(
        tuple(messages),
        (),
        context_window(model_gateway),
        model_gateway,
        media_inputs=media_inputs,
    ).within_budget:
        return compaction
    return model_step.prepare_conversation(
        messages,
        model_gateway,
        allow_tools=False,
        user_goal=user_goal,
        created_at=created_at,
        **({"media_inputs": media_inputs} if media_inputs else {}),
    )


def record_compaction(
    compaction: ConversationCompactionResult | None,
    *,
    model_step: HarnessModelStep,
    model_gateway: ModelGatewayPort,
    context: HarnessContext,
    emitted_events: list[HarnessEventDraft],
    metadata: dict[str, object],
) -> dict[str, object]:
    if compaction is None or not compaction.compacted:
        return metadata
    emitted_events.append(
        context_compacted_event(compaction, attempt_number=context.attempt.number)
    )
    previous_count = metadata.get("conversation_compaction_count", 0)
    compaction_count = (
        previous_count
        if isinstance(previous_count, int) and not isinstance(previous_count, bool)
        else 0
    )
    model_step.prepare_provider_continuation(model_gateway, compaction)
    return {
        **metadata,
        "conversation_compaction_count": compaction_count + 1,
        "conversation_tokens_after_compaction": compaction.after_tokens,
    }


def prepare_bounded_conversation(
    messages: list[SessionMessage],
    model_gateway: ModelGatewayPort,
    *,
    allow_tools: bool,
    available_tools: tuple[ModelToolDefinition, ...],
    conversation_compactor: ConversationCompactorPort | None,
    conversation_token_budget: int | None,
    compaction_hook: CompactionHook | None,
    user_goal: str,
    created_at: datetime,
    media_inputs: tuple[ModelMediaInput, ...] = (),
) -> ConversationCompactionResult | None:
    tools = available_tools if allow_tools else ()
    window = context_window(model_gateway)
    budget = min(conversation_token_budget or window.compact_at, window.compact_at)
    original = tuple(messages)
    result = _compact(
        original,
        conversation_compactor,
        compaction_hook,
        user_goal=user_goal,
        max_tokens=budget,
        created_at=created_at,
    )
    if result is not None:
        messages[:] = result.messages
    attempted = (result.provenance,) if result is not None else ()
    plan = build_context_plan(
        tuple(messages),
        tools,
        window,
        model_gateway,
        media_inputs=media_inputs,
        attempted_strategies=attempted,
    )
    if not plan.within_budget and conversation_compactor is not None:
        strict_budget = max(
            1,
            budget - (plan.estimated_input_tokens - plan.input_token_limit) - 1,
        )
        result = _compact(
            original,
            conversation_compactor,
            compaction_hook,
            user_goal=user_goal,
            max_tokens=strict_budget,
            created_at=created_at,
        )
        assert result is not None
        messages[:] = result.messages
        plan = build_context_plan(
            tuple(messages),
            tools,
            window,
            model_gateway,
            media_inputs=media_inputs,
            attempted_strategies=(*attempted, "strict_original_history_retry", result.provenance),
        )
    if not plan.within_budget:
        raise ContextWindowExceededError(plan)
    return result


def _compact(
    messages: tuple[SessionMessage, ...],
    compactor: ConversationCompactorPort | None,
    hook: CompactionHook | None,
    *,
    user_goal: str,
    max_tokens: int,
    created_at: datetime,
) -> ConversationCompactionResult | None:
    if compactor is None:
        return None
    if hook is not None:
        hook.pre_compact(messages, max_tokens=max_tokens)
    result = compactor.compact_conversation(
        messages,
        user_goal=user_goal,
        max_tokens=max_tokens,
        created_at=created_at,
    )
    if hook is not None:
        hook.post_compact(result)
    return result

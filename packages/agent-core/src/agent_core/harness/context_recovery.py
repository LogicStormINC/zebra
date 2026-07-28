from __future__ import annotations

from datetime import datetime

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.harness.context_window import ContextWindowExceededError
from agent_core.harness.hooks import CompactionHook
from agent_core.harness.model_request import build_context_plan, context_window
from agent_core.ports.conversation_compactor import (
    ConversationCompactionResult,
    ConversationCompactorPort,
)
from agent_core.ports.model_gateway import ModelGatewayPort


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

from collections.abc import Callable
from dataclasses import replace

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelContextWindow,
    ModelTextDelta,
    ModelToolDefinition,
)
from agent_core.harness.context_window import ContextWindowPlan, plan_context_window
from agent_core.ports.model_gateway import (
    ModelContextWindowPort,
    ModelGatewayPort,
    ModelTokenCounterPort,
    StreamingModelGatewayPort,
)


def context_window(gateway: ModelGatewayPort) -> ModelContextWindow:
    return (
        gateway.context_window
        if isinstance(gateway, ModelContextWindowPort)
        else ModelContextWindow()
    )


def build_context_plan(
    messages: tuple[SessionMessage, ...],
    tools: tuple[ModelToolDefinition, ...],
    window: ModelContextWindow,
    gateway: ModelGatewayPort,
    *,
    attempted_strategies: tuple[str, ...] = (),
) -> ContextWindowPlan:
    counter = gateway.count_input_tokens if isinstance(gateway, ModelTokenCounterPort) else None
    return plan_context_window(
        messages,
        tools,
        window,
        token_counter=counter,
        attempted_strategies=attempted_strategies,
    )


def with_context_plan(
    completion: ModelCompletion,
    plan: ContextWindowPlan,
) -> ModelCompletion:
    return replace(
        completion,
        call_metadata=replace(
            completion.call_metadata,
            estimated_input_tokens=plan.estimated_input_tokens,
            input_token_limit=plan.input_token_limit,
            token_estimate_method=plan.estimate_method,
        ),
    )


def complete_model(
    gateway: ModelGatewayPort,
    messages: list[SessionMessage],
    tools: tuple[ModelToolDefinition, ...],
    *,
    model_call_id: str,
    on_delta: Callable[[str, ModelTextDelta], None],
) -> ModelCompletion:
    if isinstance(gateway, StreamingModelGatewayPort):
        return gateway.complete_stream(
            messages,
            tools=tools,
            on_text_delta=lambda delta: on_delta(model_call_id, delta),
        )
    return gateway.complete(messages, tools=tools)

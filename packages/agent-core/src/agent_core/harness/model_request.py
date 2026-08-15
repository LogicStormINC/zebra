from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_media import (
    ModelMediaInput,
    ModelMediaUnsupportedError,
)
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelContextWindow,
    ModelInvocationPolicy,
    ModelTextDelta,
    ModelToolDefinition,
)
from agent_core.harness.context_window import ContextWindowPlan, plan_context_window
from agent_core.ports.model_gateway import (
    ModelContextWindowPort,
    ModelGatewayPort,
    ModelMediaCapabilityPort,
    ModelMediaTokenCounterPort,
    ModelResponseRejectedError,
    ModelTokenCounterPort,
    PolicyAwareModelGatewayPort,
    StreamingModelGatewayPort,
)

_MODEL_RESPONSE_REPAIR_LIMIT = 1


def allowed_response_repairs(
    max_model_calls: int | None,
    model_calls_used: int,
) -> int:
    if model_calls_used < 0:
        raise ValueError("model_calls_used must not be negative")
    return int(max_model_calls is None or model_calls_used + 1 < max_model_calls)


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
    media_inputs: tuple[ModelMediaInput, ...] = (),
    attempted_strategies: tuple[str, ...] = (),
) -> ContextWindowPlan:
    counter = gateway.count_input_tokens if isinstance(gateway, ModelTokenCounterPort) else None
    media_tokens = _media_tokens(gateway, media_inputs, tools=tools)
    return plan_context_window(
        messages,
        tools,
        window,
        token_counter=counter,
        media_tokens=media_tokens,
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
    media_inputs: tuple[ModelMediaInput, ...] = (),
    model_call_id: str,
    on_delta: Callable[[str, ModelTextDelta], None],
    response_repair_limit: int = _MODEL_RESPONSE_REPAIR_LIMIT,
    invocation_policy: ModelInvocationPolicy | None = None,
) -> ModelCompletion:
    if not 0 <= response_repair_limit <= _MODEL_RESPONSE_REPAIR_LIMIT:
        raise ValueError("response_repair_limit must be zero or one")
    request_messages = messages
    repair_count = 0
    rejected: ModelResponseRejectedError | None = None
    next_delta_index = 0
    attempt_deltas: list[ModelTextDelta] = []

    def emit(delta: ModelTextDelta) -> None:
        nonlocal next_delta_index
        on_delta(
            model_call_id,
            ModelTextDelta(index=next_delta_index, content=delta.content),
        )
        next_delta_index += 1

    def capture(delta: ModelTextDelta) -> None:
        attempt_deltas.append(delta)
        emit(delta)

    while True:
        attempt_deltas.clear()
        try:
            streaming = invocation_policy is None and isinstance(
                gateway, StreamingModelGatewayPort
            )
            _validate_media_request(
                gateway,
                media_inputs,
                tools=tools,
                streaming=streaming,
            )
            completion = (
                _complete_stream(
                    cast(StreamingModelGatewayPort, gateway),
                    request_messages,
                    tools=tools,
                    media_inputs=media_inputs,
                    on_text_delta=capture,
                )
                if streaming
                else _complete(
                    gateway,
                    request_messages,
                    tools=tools,
                    media_inputs=media_inputs,
                    invocation_policy=invocation_policy,
                )
            )
        except ModelResponseRejectedError as error:
            public_output_committed = bool(attempt_deltas)
            if (
                not error.retryable
                or public_output_committed
                or repair_count >= response_repair_limit
            ):
                if repair_count:
                    raise error.after_repairs(
                        repair_count,
                        initial_reason=(rejected.reason if rejected else error.reason),
                    ) from error
                raise
            rejected = error
            repair_count += 1
            request_messages = [*messages, _model_response_repair_message(error)]
            continue
        if rejected is None:
            return completion
        return replace(
            completion,
            call_metadata=replace(
                completion.call_metadata,
                response_repair_count=(
                    completion.call_metadata.response_repair_count + repair_count
                ),
                normalized_error=rejected.reason,
            ),
        )


def _media_tokens(
    gateway: ModelGatewayPort,
    media_inputs: tuple[ModelMediaInput, ...],
    *,
    tools: tuple[ModelToolDefinition, ...],
) -> int:
    if not media_inputs:
        return 0
    _validate_media_request(gateway, media_inputs, tools=tools, streaming=False)
    if not isinstance(gateway, ModelMediaTokenCounterPort):
        raise ModelMediaUnsupportedError("model profile does not provide a media token estimate")
    tokens = gateway.estimate_media_tokens(media_inputs)
    if tokens < 0:
        raise ValueError("model media token estimate must not be negative")
    return tokens


def _validate_media_request(
    gateway: ModelGatewayPort,
    media_inputs: tuple[ModelMediaInput, ...],
    *,
    tools: tuple[ModelToolDefinition, ...],
    streaming: bool,
) -> None:
    if not media_inputs:
        return
    if not isinstance(gateway, ModelMediaCapabilityPort):
        raise ModelMediaUnsupportedError("model profile does not support image input")
    gateway.media_capabilities.validate_request(
        media_inputs,
        has_tools=bool(tools),
        streaming=streaming,
    )


def _complete(
    gateway: ModelGatewayPort,
    messages: list[SessionMessage],
    *,
    tools: tuple[ModelToolDefinition, ...],
    media_inputs: tuple[ModelMediaInput, ...],
    invocation_policy: ModelInvocationPolicy | None,
) -> ModelCompletion:
    if invocation_policy is not None:
        if not isinstance(gateway, PolicyAwareModelGatewayPort):
            raise ModelResponseRejectedError(
                "model gateway does not support required invocation policy",
                phase="request",
                retryable=False,
            )
        return gateway.complete_with_policy(
            messages,
            tools=tools,
            media_inputs=media_inputs,
            invocation_policy=invocation_policy,
        )
    if media_inputs:
        return gateway.complete(messages, tools=tools, media_inputs=media_inputs)
    return gateway.complete(messages, tools=tools)


def _complete_stream(
    gateway: StreamingModelGatewayPort,
    messages: list[SessionMessage],
    *,
    tools: tuple[ModelToolDefinition, ...],
    media_inputs: tuple[ModelMediaInput, ...],
    on_text_delta: Callable[[ModelTextDelta], None],
) -> ModelCompletion:
    if media_inputs:
        return gateway.complete_stream(
            messages,
            tools=tools,
            media_inputs=media_inputs,
            on_text_delta=on_text_delta,
        )
    return gateway.complete_stream(messages, tools=tools, on_text_delta=on_text_delta)


def _model_response_repair_message(
    error: ModelResponseRejectedError,
) -> SessionMessage:
    tool = f" for {error.provider_tool_name}" if error.provider_tool_name else ""
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.SYSTEM,
        content=(
            "Internal model-response repair: the previous response was rejected "
            f"during {error.phase}{tool} before any newly proposed tool was executed. "
            "Produce a fresh response. Tool arguments must be exactly one valid JSON "
            "object matching the advertised schema. Do not repeat tools whose results "
            "are already present in the conversation, and do not discuss this repair."
        ),
        created_at=datetime.now(UTC),
        metadata={"internal_model_response_repair": True},
    )

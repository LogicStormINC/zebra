from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelInvocationPolicy,
    ModelReasoningEffort,
    ModelRole,
    ModelThinkingMode,
    ModelToolChoice,
    ModelToolDefinition,
)
from agent_integrations import ModelProviderSettings, build_model_gateway
from zebra_agent_config import load_settings


def test_real_deepseek_non_thinking_tool_round_trip() -> None:
    settings = load_settings()
    model = settings.model
    try:
        gateway = build_model_gateway(
            ModelProviderSettings(
                provider=model.provider,
                api_key_env=model.api_key_env,
                base_url=model.base_url,
                model=model.model,
                max_retries=model.max_retries,
            )
        )
    except ValueError as exc:
        if "missing API key" not in str(exc):
            raise
        pytest.skip(f"{settings.model.api_key_env} is not configured")
    user_message = _message(
        MessageRole.USER,
        "Call smoke.echo exactly once with value zebra-ready, then report the result.",
    )
    first = gateway.complete(
        [user_message],
        tools=(
            ModelToolDefinition(
                name="smoke.echo",
                description="Return the provided value unchanged.",
                parameters={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            ),
        ),
        invocation_policy=ModelInvocationPolicy(
            tool_choice=ModelToolChoice.REQUIRED,
            max_output_tokens=256,
        ),
    )
    assert first.call_metadata.thinking_mode == "disabled"
    assert len(first.tool_calls) == 1
    tool_call = first.tool_calls[0]
    final = gateway.complete(
        [
            user_message,
            first.assistant_message,
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.TOOL,
                content=str(tool_call.arguments.get("value", "")),
                created_at=datetime.now(UTC),
                tool_call_id=tool_call.provider_call_id,
            ),
        ],
        invocation_policy=ModelInvocationPolicy(max_output_tokens=256),
    )

    assert final.assistant_message.content.strip()


def test_real_deepseek_thinking_tool_round_trip() -> None:
    settings = load_settings()
    model = settings.model
    try:
        gateway = build_model_gateway(
            ModelProviderSettings(
                provider=model.provider,
                api_key_env=model.api_key_env,
                base_url=model.base_url,
                model=model.model,
                max_retries=model.max_retries,
            )
        )
    except ValueError as exc:
        if "missing API key" not in str(exc):
            raise
        pytest.skip(f"{settings.model.api_key_env} is not configured")
    tool = ModelToolDefinition(
        name="smoke.echo",
        description="Return the provided value unchanged.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    policy = ModelInvocationPolicy(
        thinking_mode=ModelThinkingMode.ENABLED,
        reasoning_effort=ModelReasoningEffort.HIGH,
        tool_choice=ModelToolChoice.AUTO,
        max_output_tokens=256,
    )
    user = _message(
        MessageRole.USER,
        "Call smoke.echo exactly once with value zebra-thinking, then report the result.",
    )

    first = gateway.complete([user], tools=(tool,), invocation_policy=policy)
    assert first.assistant_message.provider_reasoning_content
    call = first.tool_calls[0]
    final = gateway.complete(
        [
            user,
            first.assistant_message,
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.TOOL,
                content=str(call.arguments.get("value", "")),
                created_at=datetime.now(UTC),
                tool_call_id=call.provider_call_id,
            ),
        ],
        tools=(tool,),
        invocation_policy=ModelInvocationPolicy(
            thinking_mode=ModelThinkingMode.ENABLED,
            reasoning_effort=ModelReasoningEffort.HIGH,
            max_output_tokens=256,
        ),
    )

    assert final.assistant_message.content.strip()


def test_real_deepseek_responses_thinking_tool_round_trip() -> None:
    settings = load_settings()
    model = settings.model
    try:
        gateway = build_model_gateway(
            ModelProviderSettings(
                provider=model.provider,
                api_key_env=model.api_key_env,
                base_url=model.base_url,
                model="deepseek-v4-flash",
                max_retries=model.max_retries,
                wire_api="responses",
            )
        )
    except ValueError as exc:
        if "missing API key" not in str(exc):
            raise
        pytest.skip(f"{settings.model.api_key_env} is not configured")
    tool = ModelToolDefinition(
        name="smoke.echo",
        description="Return the provided value unchanged.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    policy = ModelInvocationPolicy(
        thinking_mode=ModelThinkingMode.ENABLED,
        reasoning_effort=ModelReasoningEffort.HIGH,
        tool_choice=ModelToolChoice.AUTO,
        max_output_tokens=256,
    )
    user = _message(
        MessageRole.USER,
        "Call smoke.echo exactly once with value zebra-responses, then report the result.",
    )

    first = gateway.complete_stream(
        [user],
        tools=(tool,),
        invocation_policy=policy,
        on_text_delta=lambda delta: None,
    )
    assert first.assistant_message.provider_reasoning_content
    call = first.tool_calls[0]
    public_deltas = []
    final = gateway.complete_stream(
        [
            user,
            first.assistant_message,
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.TOOL,
                content=str(call.arguments.get("value", "")),
                created_at=datetime.now(UTC),
                tool_call_id=call.provider_call_id,
            ),
        ],
        tools=(tool,),
        invocation_policy=ModelInvocationPolicy(
            thinking_mode=ModelThinkingMode.ENABLED,
            reasoning_effort=ModelReasoningEffort.HIGH,
            max_output_tokens=256,
        ),
        on_text_delta=public_deltas.append,
    )

    assert final.assistant_message.content.strip()
    assert "".join(delta.content for delta in public_deltas).strip()

    review_deltas = []
    review = gateway.complete_stream(
        [_message(MessageRole.USER, "Reply with exactly: zebra-reviewed")],
        invocation_policy=ModelInvocationPolicy(
            role=ModelRole.REVIEWER,
            thinking_mode=ModelThinkingMode.ENABLED,
            reasoning_effort=ModelReasoningEffort.HIGH,
            max_output_tokens=128,
        ),
        on_text_delta=review_deltas.append,
    )

    assert review.call_metadata.resolved_model == "deepseek-v4-pro"
    assert review.assistant_message.provider_reasoning_content
    assert "zebra-reviewed" in "".join(
        delta.content for delta in review_deltas
    ).lower()


def _message(role: MessageRole, content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=role,
        content=content,
        created_at=datetime.now(UTC),
    )

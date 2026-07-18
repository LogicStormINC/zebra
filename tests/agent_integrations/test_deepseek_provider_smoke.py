from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelInvocationPolicy,
    ModelToolChoice,
    ModelToolDefinition,
)
from agent_integrations import build_model_gateway
from zebra_agent_config import load_settings


def test_real_deepseek_non_thinking_tool_round_trip() -> None:
    settings = load_settings()
    try:
        gateway = build_model_gateway(settings)
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


def _message(role: MessageRole, content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=role,
        content=content,
        created_at=datetime.now(UTC),
    )

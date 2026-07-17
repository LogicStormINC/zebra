import os
from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelInvocationPolicy, ModelToolChoice, ModelToolDefinition
from agent_integrations import build_deepseek_beta_gateway
from zebra_agent_config import load_settings


def test_real_deepseek_beta_capabilities() -> None:
    if os.environ.get("ZEBRA_DEEPSEEK_BETA_SMOKE") != "1":
        pytest.skip("set ZEBRA_DEEPSEEK_BETA_SMOKE=1 for the real beta provider smoke")
    settings = load_settings()
    gateway = build_deepseek_beta_gateway(settings)

    strict = gateway.complete_strict_tools(
        [_message("Call smoke.echo exactly once with value beta-ready.")],
        tools=(
            ModelToolDefinition(
                name="smoke.echo",
                description="Echo the supplied value.",
                parameters={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            ),
        ),
        invocation_policy=ModelInvocationPolicy(tool_choice=ModelToolChoice.REQUIRED),
        allow_stable_fallback=False,
    )
    assert strict.endpoint_variant == "beta"
    assert strict.completion.tool_calls[0].arguments["value"] == "beta-ready"

    fim = gateway.complete_fim(
        "def add_one(value):\n    return value",
        suffix="\n\nassert add_one(1) == 2",
        max_tokens=128,
        allow_stable_fallback=False,
    )
    assert fim.endpoint_variant == "beta"
    assert fim.text.strip()

    prefix = gateway.complete_chat_prefix(
        [_message("Return a Python pass statement and nothing else.")],
        prefix="```python\n",
        max_tokens=32,
        stop=("```",),
        allow_stable_fallback=False,
    )
    assert prefix.endpoint_variant == "beta"
    assert prefix.text.startswith("```python\n")


def _message(content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content=content,
        created_at=datetime.now(UTC),
    )

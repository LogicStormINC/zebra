import json
from datetime import UTC, datetime

import httpx
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelInvocationPolicy,
    ModelToolChoice,
    ModelToolDefinition,
)
from agent_integrations import OpenAICompatibleModelGateway


def test_deepseek_required_invocation_serializes_one_selected_tool() -> None:
    _assert_required_invocation("deepseek", "deepseek-v4-flash")


def test_openai_required_invocation_serializes_one_selected_tool() -> None:
    _assert_required_invocation("openai", "gpt-test")


def test_qwen_required_invocation_keeps_native_safety_flags() -> None:
    captured = _assert_required_invocation("qwen", "qwen-test")

    assert captured["enable_thinking"] is False
    assert captured["enable_search"] is False
    assert captured["enable_code_interpreter"] is False


def _assert_required_invocation(provider: str, model: str) -> dict[str, object]:
    captured = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        tool_name = captured["tools"][0]["function"]["name"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": tool_name, "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    gateway = OpenAICompatibleModelGateway(
        provider_name=provider,
        base_url=f"https://api.{provider}.test",
        api_key="test-only",
        model_name=model,
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    completion = gateway.complete_with_policy(
        [
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content="Collect required evidence.",
                created_at=datetime(2026, 8, 13, tzinfo=UTC),
            )
        ],
        tools=(
            ModelToolDefinition(
                name="evidence.lookup",
                description="Read trusted evidence.",
                parameters={"type": "object", "properties": {}},
            ),
        ),
        invocation_policy=ModelInvocationPolicy(tool_choice=ModelToolChoice.REQUIRED),
    )

    assert captured["tool_choice"] == "required"
    assert len(captured["tools"]) == 1
    assert completion.tool_calls[0].name == "evidence.lookup"
    return captured

import json
from datetime import UTC, datetime

import httpx
import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelToolDefinition
from agent_integrations import (
    DEEPSEEK_BETA_PROFILES,
    DeepSeekBetaGateway,
    ModelProviderSettings,
    build_deepseek_beta_gateway,
)
from zebra_agent_config import load_settings


def test_strict_tools_use_only_beta_endpoint_and_mark_every_function_strict() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _tool_completion()

    result = _gateway(handle).complete_strict_tools(
        [_message("Use the tool")],
        tools=(_strict_tool(),),
    )

    body = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://api.deepseek.com/beta/chat/completions"
    assert body["tools"][0]["function"]["strict"] is True
    assert body["thinking"] == {"type": "disabled"}
    assert result.endpoint_variant == "beta"
    assert result.profile_id == "deepseek-v4-beta-strict-tools-v1"
    assert len(result.completion.tool_calls) == 1


@pytest.mark.parametrize(
    ("schema", "error"),
    [
        (
            {"type": "object", "properties": {"value": {"type": "string"}}},
            "required list",
        ),
        (
            {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            "additionalProperties=false",
        ),
        (
            {
                "type": "object",
                "properties": {"value": {"type": "string", "minLength": 1}},
                "required": ["value"],
                "additionalProperties": False,
            },
            "unsupported keywords",
        ),
        (
            {
                "type": "object",
                "properties": {"value": {"type": "null"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            "unsupported type",
        ),
    ],
)
def test_strict_schema_checker_rejects_incompatible_dialect_before_http(
    schema: dict[str, object],
    error: str,
) -> None:
    called = False

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return _tool_completion()

    with pytest.raises(ValueError, match=error):
        _gateway(handle).complete_strict_tools(
            [_message("Use the tool")],
            tools=(ModelToolDefinition("smoke.echo", "Echo.", schema),),
        )

    assert called is False


def test_strict_schema_checker_accepts_nested_arrays_anyof_and_defs() -> None:
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "anyOf": [
                        {"type": "string", "pattern": "^[a-z]+$"},
                        {"$ref": "#/$defs/count"},
                    ]
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
        "$defs": {"count": {"type": "integer", "minimum": 0}},
    }

    result = _gateway(lambda request: _tool_completion()).complete_strict_tools(
        [_message("Use the tool")],
        tools=(ModelToolDefinition("smoke.echo", "Echo.", schema),),
    )

    assert result.endpoint_variant == "beta"


def test_strict_beta_failure_falls_back_once_to_stable_without_strict_flag() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "/beta/" in str(request.url):
            return httpx.Response(503)
        return _tool_completion()

    result = _gateway(handle).complete_strict_tools(
        [_message("Use the tool")],
        tools=(_strict_tool(),),
    )

    assert [str(request.url) for request in requests] == [
        "https://api.deepseek.com/beta/chat/completions",
        "https://api.deepseek.com/chat/completions",
    ]
    stable_body = json.loads(requests[1].content)
    assert "strict" not in stable_body["tools"][0]["function"]
    assert result.endpoint_variant == "stable_fallback"
    assert result.fallback_reason == "provider_unavailable"


def test_fim_uses_beta_completions_and_collects_public_usage() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-pro",
                "choices": [{"text": " + 1", "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    result = _gateway(handle, model="deepseek-v4-pro").complete_fim(
        "return value",
        suffix="\n",
        max_tokens=32,
    )

    assert captured["url"] == "https://api.deepseek.com/beta/completions"
    assert captured["body"] == {
        "model": "deepseek-v4-pro",
        "prompt": "return value",
        "suffix": "\n",
        "max_tokens": 32,
    }
    assert result.text == " + 1"
    assert result.usage.total_tokens == 5


def test_chat_prefix_uses_beta_and_discards_private_reasoning() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": "pass\n```",
                            "reasoning_content": "private chain",
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    result = _gateway(handle).complete_chat_prefix(
        [_message("Write Python")],
        prefix="```python\n",
        stop=("```",),
    )

    assert captured["messages"][-1] == {
        "role": "assistant",
        "content": "```python\n",
        "prefix": True,
    }
    assert captured["thinking"] == {"type": "disabled"}
    assert result.text == "```python\npass\n```"
    assert "private chain" not in repr(result)


def test_fim_beta_failure_falls_back_to_stable_chat_without_state_mutation() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "/beta/" in str(request.url):
            return httpx.Response(404)
        return _text_completion("middle")

    result = _gateway(handle).complete_fim("before", suffix="after")

    assert [request.url.path for request in requests] == [
        "/beta/completions",
        "/chat/completions",
    ]
    assert result.endpoint_variant == "stable_fallback"
    assert result.fallback_reason == "http_error"
    assert result.text == "middle"


def test_beta_gateway_is_disabled_by_default_and_validates_endpoint_isolation() -> None:
    assert all(profile.enabled_by_default is False for profile in DEEPSEEK_BETA_PROFILES)
    loaded = load_settings(env={})
    settings = ModelProviderSettings(
        provider=loaded.model.provider,
        api_key_env=loaded.model.api_key_env,
        base_url=loaded.model.base_url,
        model=loaded.model.model,
        deepseek_beta_enabled=loaded.model.deepseek_beta_enabled,
        deepseek_beta_base_url=loaded.model.deepseek_beta_base_url,
    )
    with pytest.raises(ValueError, match="disabled"):
        build_deepseek_beta_gateway(settings, env={"DEEPSEEK_API_KEY": "secret"})
    with pytest.raises(ValueError, match="stable endpoint"):
        DeepSeekBetaGateway(
            stable_base_url="https://api.deepseek.com/beta",
            beta_base_url="https://api.deepseek.com/beta",
            api_key="secret",
            model_name="deepseek-v4-flash",
        )


def _gateway(handler, *, model: str = "deepseek-v4-flash") -> DeepSeekBetaGateway:
    return DeepSeekBetaGateway(
        stable_base_url="https://api.deepseek.com",
        beta_base_url="https://api.deepseek.com/beta",
        api_key="secret",
        model_name=model,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _message(content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content=content,
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
    )


def _strict_tool() -> ModelToolDefinition:
    return ModelToolDefinition(
        name="smoke.echo",
        description="Echo a value.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )


def _tool_completion() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "smoke__echo",
                                    "arguments": '{"value":"ok"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
    )


def _text_completion(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "deepseek-v4-flash",
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        },
    )

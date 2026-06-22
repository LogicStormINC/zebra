import json
from datetime import UTC, datetime

import httpx
import pytest
from agent_core.domain.identifiers import MessageId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_integrations import OpenAICompatibleModelGateway, build_model_gateway
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_openai_compatible_gateway_serializes_messages_and_parses_completion() -> None:
    captured: dict[str, object] = {}
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: _handle_basic_completion(request, captured)
        )
    )
    gateway = OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-flash",
        client=client,
    )

    completion = gateway.complete(
        [
            SessionMessage(
                message_id=_message_id(),
                role=MessageRole.SYSTEM,
                content="You are a helpful assistant.",
                created_at=_created_at(),
            ),
            SessionMessage(
                message_id=_message_id(),
                role=MessageRole.USER,
                content="Hello",
                created_at=_created_at(),
            ),
        ]
    )

    assert captured["path"] == "/chat/completions"
    assert captured["authorization"] == "Bearer secret"
    assert captured["json"] == {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ],
        "stream": False,
    }
    assert completion.assistant_message.content == "Hi there"
    assert completion.call_metadata.provider == "deepseek"
    assert completion.call_metadata.model_name == "deepseek-v4-flash"
    assert completion.call_metadata.usage.total_tokens == 12


def test_openai_compatible_gateway_parses_tool_calls() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(_handle_tool_call_completion)
    )
    gateway = OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-flash",
        client=client,
    )

    completion = gateway.complete(
        [
            SessionMessage(
                message_id=_message_id(),
                role=MessageRole.USER,
                content="Read the README",
                created_at=_created_at(),
            )
        ]
    )

    assert completion.assistant_message.content == "Tool calls proposed."
    assert len(completion.tool_calls) == 1
    assert completion.tool_calls[0].name == "files.read"
    assert completion.tool_calls[0].arguments == {"path": "README.md"}


def test_build_model_gateway_raises_when_api_key_is_missing() -> None:
    with pytest.raises(ValueError, match="missing API key"):
        build_model_gateway(_settings(), env={})


def test_build_model_gateway_uses_configured_env_name() -> None:
    gateway = build_model_gateway(
        _settings(),
        env={"DEEPSEEK_API_KEY": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(_handle_basic_completion_no_capture)),
    )

    assert gateway.complete(
        [
            SessionMessage(
                message_id=_message_id(),
                role=MessageRole.USER,
                content="Hello",
                created_at=_created_at(),
            )
        ]
    ).call_metadata.provider == "deepseek"


def _settings() -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
        ),
    )


def _handle_basic_completion(
    request: httpx.Request,
    captured: dict[str, object],
) -> httpx.Response:
    captured["path"] = request.url.path
    captured["authorization"] = request.headers.get("Authorization")
    captured["json"] = json.loads(request.content.decode("utf-8"))
    return _json_response(
        {
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hi there",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 7,
                "total_tokens": 12,
            },
        }
    )


def _handle_basic_completion_no_capture(request: httpx.Request) -> httpx.Response:
    del request
    return _json_response(
        {
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hi there",
                    }
                }
            ],
        }
    )


def _handle_tool_call_completion(request: httpx.Request) -> httpx.Response:
    del request
    return _json_response(
        {
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "files.read",
                                    "arguments": "{\"path\":\"README.md\"}",
                                },
                            }
                        ],
                    }
                }
            ],
        }
    )


def _json_response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(status_code=200, json=payload)


def _created_at() -> datetime:
    return datetime(2026, 6, 22, 12, 0, tzinfo=UTC)


def _message_id() -> MessageId:
    return new_message_id()

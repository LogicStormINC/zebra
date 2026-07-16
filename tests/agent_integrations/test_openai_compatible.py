import json
from datetime import UTC, datetime

import httpx
import pytest
from agent_core.domain.identifiers import MessageId, new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCall
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


def test_openai_compatible_gateway_serializes_tools_and_restores_internal_name() -> None:
    captured: dict[str, object] = {}
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: _handle_advertised_tool_call(request, captured)
        )
    )
    gateway = OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-flash",
        client=client,
    )
    tool = ModelToolDefinition(
        name="files.read",
        description="Read a workspace file.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    )

    completion = gateway.complete([_user_message("Read README.md")], tools=(tool,))

    assert captured["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "files__read",
                "description": "Read a workspace file.",
                "parameters": dict(tool.parameters),
            },
        }
    ]
    assert completion.tool_calls[0].name == "files.read"


def test_openai_compatible_gateway_rejects_unadvertised_tool_call() -> None:
    gateway = OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-flash",
        client=httpx.Client(transport=httpx.MockTransport(_handle_unknown_tool_call)),
    )
    tool = ModelToolDefinition(
        name="files.read",
        description="Read a workspace file.",
        parameters={"type": "object", "properties": {}},
    )

    with pytest.raises(ValueError, match="unadvertised tool call"):
        gateway.complete([_user_message("Run something")], tools=(tool,))


def test_openai_compatible_gateway_serializes_tool_result_conversation() -> None:
    requests: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        if len(requests) == 1:
            return _tool_call_response("files__read", '{"path":"proof.txt"}')
        return _json_response(
            {
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "The proof says zebra-ready.",
                        }
                    }
                ],
            }
        )

    gateway = OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-flash",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    tool = ModelToolDefinition(
        name="files.read",
        description="Read a workspace file.",
        parameters={"type": "object", "properties": {}},
    )
    user_message = _user_message("Read proof.txt")
    first = gateway.complete([user_message], tools=(tool,))
    tool_call = first.tool_calls[0]

    final = gateway.complete(
        [
            user_message,
            first.assistant_message,
            SessionMessage(
                message_id=_message_id(),
                role=MessageRole.TOOL,
                content="zebra-ready",
                created_at=_created_at(),
                tool_call_id=tool_call.provider_call_id,
            ),
        ]
    )

    assert requests[1]["messages"][-2:] == [
        {
            "role": "assistant",
            "content": "Tool calls proposed.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "files__read",
                        "arguments": '{"path":"proof.txt"}',
                    },
                }
            ],
        },
        {"role": "tool", "content": "zebra-ready", "tool_call_id": "call_1"},
    ]
    assert "tools" not in requests[1]
    assert final.assistant_message.content == "The proof says zebra-ready."


def test_openai_compatible_gateway_serializes_provider_tool_presentation() -> None:
    requests: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        return _json_response(
            {
                "model": "deepseek-v4-flash",
                "choices": [{"message": {"role": "assistant", "content": "done"}}],
            }
        )

    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="mcp.fixture.echo",
        arguments={"value": "approved"},
        created_at=_created_at(),
        provider_call_id="call_bridge",
        provider_tool_name="agent.tools.call",
        provider_arguments={
            "name": "mcp.fixture.echo",
            "arguments": {"value": "approved"},
        },
    )
    gateway = OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-flash",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    gateway.complete(
        [
            _user_message("Use the external tool"),
            SessionMessage(
                message_id=_message_id(),
                role=MessageRole.ASSISTANT,
                content="Calling selected MCP tool.",
                created_at=_created_at(),
                tool_calls=(tool_call,),
            ),
            SessionMessage(
                message_id=_message_id(),
                role=MessageRole.TOOL,
                content="echo:approved",
                created_at=_created_at(),
                tool_call_id="call_bridge",
            ),
        ]
    )

    assert requests[0]["messages"][-2]["tool_calls"] == [
        {
            "id": "call_bridge",
            "type": "function",
            "function": {
                "name": "agent__tools__call",
                "arguments": (
                    '{"arguments":{"value":"approved"},"name":"mcp.fixture.echo"}'
                ),
            },
        }
    ]


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


def test_build_model_gateway_loads_api_key_from_dotenv_local(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.local").write_text(
        "DEEPSEEK_API_KEY=dot-env-secret\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    gateway = build_model_gateway(
        _settings(),
        client=httpx.Client(transport=httpx.MockTransport(_handle_basic_completion_no_capture)),
    )
    assert (
        gateway.complete(
            [
                SessionMessage(
                    message_id=_message_id(),
                    role=MessageRole.USER,
                    content="Hello",
                    created_at=_created_at(),
                )
            ]
        ).assistant_message.content
        == "Hi there"
    )


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


def _handle_advertised_tool_call(
    request: httpx.Request,
    captured: dict[str, object],
) -> httpx.Response:
    payload = json.loads(request.content.decode("utf-8"))
    captured["tools"] = payload["tools"]
    return _tool_call_response("files__read", '{"path":"README.md"}')


def _handle_unknown_tool_call(request: httpx.Request) -> httpx.Response:
    del request
    return _tool_call_response("command__run", '{"command":["pwd"]}')


def _tool_call_response(name: str, arguments: str) -> httpx.Response:
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
                                "function": {"name": name, "arguments": arguments},
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


def _user_message(content: str) -> SessionMessage:
    return SessionMessage(
        message_id=_message_id(),
        role=MessageRole.USER,
        content=content,
        created_at=_created_at(),
    )

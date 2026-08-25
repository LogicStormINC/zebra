import json
from datetime import UTC, datetime

import httpx
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
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_integrations import (
    DeepSeekResponsesModelGateway,
    ModelProviderSettings,
    build_model_gateway,
)


def test_factory_selects_responses_only_when_explicit() -> None:
    gateway = build_model_gateway(
        ModelProviderSettings(
            provider="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            wire_api="responses",
        ),
        env={"DEEPSEEK_API_KEY": "secret"},
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: _response("done"))
        ),
    )

    assert isinstance(gateway, DeepSeekResponsesModelGateway)


def test_responses_maps_thinking_tool_call_and_replays_reasoning() -> None:
    requests: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return _response(
                "",
                reasoning="private plan",
                function_call={
                    "call_id": "call-1",
                    "name": "files__read",
                    "arguments": '{"path":"proof.txt"}',
                },
            )
        return _response("proof received")

    gateway = _gateway(handle)
    policy = ModelInvocationPolicy(
        thinking_mode=ModelThinkingMode.ENABLED,
        reasoning_effort=ModelReasoningEffort.LOW,
        tool_choice=ModelToolChoice.AUTO,
        max_output_tokens=512,
    )
    user = _message("read proof")
    tool = _tool()
    first = gateway.complete([user], tools=(tool,), invocation_policy=policy)
    call = first.tool_calls[0]
    final = gateway.complete(
        [
            user,
            first.assistant_message,
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.TOOL,
                content="zebra-ready",
                created_at=datetime.now(UTC),
                tool_call_id=call.provider_call_id,
            ),
        ],
        tools=(tool,),
        invocation_policy=policy,
    )

    first_request = requests[0]
    assert first_request["reasoning"] == {"effort": "low"}
    assert first_request["tool_choice"] == "auto"
    assert first_request["max_output_tokens"] == 512
    assert first_request["tools"] == [
        {
            "type": "function",
            "name": "files__read",
            "description": "Read a file.",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    replay = requests[1]["input"]
    assert {"type": "reasoning", "content": [
        {"type": "reasoning_text", "text": "private plan"}
    ]} in replay
    assert final.assistant_message.provider_reasoning_content is None
    assert "private" not in final.assistant_message.content
    assert final.call_metadata.prompt_version == "zebra-deepseek-responses-v1"


def test_responses_stream_uses_semantic_terminal_and_hides_reasoning() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        del request
        terminal = _response_payload("public", reasoning="private chain")
        return httpx.Response(
            200,
            text="\n".join(
                [
                    'event: response.created',
                    'data: {"type":"response.created","sequence_number":0}',
                    'event: response.reasoning_text.delta',
                    (
                        'data: {"type":"response.reasoning_text.delta",'
                        '"sequence_number":2,"delta":"private chain"}'
                    ),
                    'event: response.output_text.delta',
                    (
                        'data: {"type":"response.output_text.delta",'
                        '"sequence_number":5,"delta":"public"}'
                    ),
                    'event: response.completed',
                    "data: "
                    + json.dumps(
                        {
                            "type": "response.completed",
                            "sequence_number": 8,
                            "response": terminal,
                        }
                    ),
                ]
            ),
        )

    deltas = []
    completion = _gateway(handle).complete_stream(
        [_message("review")],
        on_text_delta=deltas.append,
    )

    assert [delta.content for delta in deltas] == ["public"]
    assert completion.assistant_message.content == "public"
    assert completion.assistant_message.provider_reasoning_content == "private chain"
    assert completion.call_metadata.time_to_first_event_ms is not None
    assert completion.call_metadata.time_to_first_public_text_ms is not None
    assert completion.call_metadata.usage.prompt_cache_hit_tokens == 7
    assert completion.call_metadata.usage.prompt_cache_miss_tokens == 5


def test_responses_rejects_provider_side_web_search_output() -> None:
    payload = _response_payload("done")
    payload["output"].insert(
        0,
        {"type": "web_search_call", "id": "ws-1", "status": "completed"},
    )
    with pytest.raises(ModelResponseRejectedError, match="provider_side_tool_not_allowed"):
        _gateway(lambda request: httpx.Response(200, json=payload)).complete(
            [_message("search")]
        )


def test_responses_rejects_unknown_output_items() -> None:
    payload = _response_payload("done")
    payload["output"].insert(0, {"type": "custom_tool_call", "name": "apply_patch"})
    with pytest.raises(ModelResponseRejectedError, match="unsupported_responses_output_item"):
        _gateway(lambda request: httpx.Response(200, json=payload)).complete(
            [_message("patch")]
        )


def test_responses_rejects_non_json_without_exposing_body() -> None:
    private_body = "<html>provider secret detail</html>"
    with pytest.raises(ModelResponseRejectedError) as caught:
        _gateway(lambda request: httpx.Response(200, text=private_body)).complete(
            [_message("review")]
        )

    assert caught.value.reason == "invalid_responses_json"
    assert caught.value.payload_size == len(private_body)
    assert "provider secret detail" not in str(caught.value)


def test_responses_supports_pro_profile() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["model"] == "deepseek-v4-pro"
        return _response("reviewed", model="deepseek-v4-pro")

    gateway = DeepSeekResponsesModelGateway(
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-pro",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    completion = gateway.complete(
        [_message("review")],
        invocation_policy=ModelInvocationPolicy(role=ModelRole.REVIEWER),
    )

    assert completion.call_metadata.resolved_model == "deepseek-v4-pro"


def test_responses_rejects_required_tool_choice_in_thinking_mode() -> None:
    called = False

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return _response("unexpected")

    with pytest.raises(ValueError, match="does not support tool_choice=required"):
        _gateway(handle).complete(
            [_message("use a tool")],
            tools=(_tool(),),
            invocation_policy=ModelInvocationPolicy(
                thinking_mode=ModelThinkingMode.ENABLED,
                tool_choice=ModelToolChoice.REQUIRED,
            ),
        )

    assert called is False


def _gateway(handler) -> DeepSeekResponsesModelGateway:
    return DeepSeekResponsesModelGateway(
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-flash",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _message(content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content=content,
        created_at=datetime.now(UTC),
    )


def _tool() -> ModelToolDefinition:
    return ModelToolDefinition(
        name="files.read",
        description="Read a file.",
        parameters={"type": "object", "properties": {}},
    )


def _response(
    text: str,
    *,
    reasoning: str | None = None,
    function_call: dict[str, object] | None = None,
    model: str = "deepseek-v4-flash",
) -> httpx.Response:
    return httpx.Response(
        200,
        json=_response_payload(
            text,
            reasoning=reasoning,
            function_call=function_call,
            model=model,
        ),
    )


def _response_payload(
    text: str,
    *,
    reasoning: str | None = None,
    function_call: dict[str, object] | None = None,
    model: str = "deepseek-v4-flash",
) -> dict[str, object]:
    output: list[dict[str, object]] = []
    if reasoning is not None:
        output.append(
            {
                "type": "reasoning",
                "content": [{"type": "reasoning_text", "text": reasoning}],
            }
        )
    if text:
        output.append(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        )
    if function_call is not None:
        output.append({"type": "function_call", **function_call})
    return {
        "id": "resp-1",
        "object": "response",
        "status": "completed",
        "model": model,
        "output": output,
        "usage": {
            "input_tokens": 12,
            "input_tokens_details": {"cached_tokens": 7},
            "output_tokens": 9,
            "output_tokens_details": {"reasoning_tokens": 4},
            "total_tokens": 21,
        },
    }

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
    ModelToolDefinition,
)
from agent_integrations import ModelProviderError, OpenAICompatibleModelGateway


def test_deepseek_routes_no_tool_planner_to_pro_reasoning_profile() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _completion("plan", model="deepseek-v4-pro")

    completion = _gateway(handle).complete(
        [_message("plan this change")],
        invocation_policy=ModelInvocationPolicy(role=ModelRole.PLANNER),
    )

    assert captured["model"] == "deepseek-v4-pro"
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "max"
    assert captured["tool_choice"] == "none"
    assert completion.call_metadata.profile_id == "deepseek-v4-pro-planner-v1"
    assert completion.call_metadata.profile_version_observed_at == "2026-07-17"


def test_deepseek_tool_request_explicitly_disables_thinking() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _completion("done")

    _gateway(handle).complete([_message("read")], tools=(_tool(),))

    assert captured["thinking"] == {"type": "disabled"}
    assert captured["tool_choice"] == "auto"
    assert "reasoning_effort" not in captured


def test_deepseek_rejects_thinking_with_tools_before_http() -> None:
    called = False

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return _completion("unexpected")

    with pytest.raises(ValueError, match="thinking with tools"):
        _gateway(handle).complete(
            [_message("read")],
            tools=(_tool(),),
            invocation_policy=ModelInvocationPolicy(
                thinking_mode=ModelThinkingMode.ENABLED,
            ),
        )

    assert called is False


def test_deepseek_stream_discards_reasoning_and_records_usage_and_finish() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            text="\n".join(
                [
                    (
                        'data: {"id":"call-1","model":"deepseek-v4-pro",'
                        '"system_fingerprint":"fp-1","choices":[{"delta":'
                        '{"reasoning_content":"private chain"}}]}'
                    ),
                    'data: {"choices":[{"delta":{"content":"public"},"finish_reason":"stop"}]}',
                    (
                        'data: {"choices":[],"usage":{"prompt_tokens":12,'
                        '"completion_tokens":5,"total_tokens":17,'
                        '"prompt_cache_hit_tokens":8,"prompt_cache_miss_tokens":4,'
                        '"completion_tokens_details":{"reasoning_tokens":3}}}'
                    ),
                    "data: [DONE]",
                ]
            ),
        )

    deltas = []
    completion = _gateway(handle).complete_stream(
        [_message("review")],
        invocation_policy=ModelInvocationPolicy(
            role=ModelRole.REVIEWER,
            reasoning_effort=ModelReasoningEffort.HIGH,
        ),
        on_text_delta=deltas.append,
    )

    assert [delta.content for delta in deltas] == ["public"]
    assert "private chain" not in completion.assistant_message.content
    metadata = completion.call_metadata
    assert metadata.model_call_id == "call-1"
    assert metadata.resolved_model == "deepseek-v4-pro"
    assert metadata.system_fingerprint == "fp-1"
    assert metadata.finish_reason == "stop"
    assert metadata.time_to_first_event_ms is not None
    assert metadata.time_to_first_public_text_ms is not None
    assert metadata.usage.reasoning_tokens == 3
    assert metadata.usage.prompt_cache_hit_tokens == 8
    assert metadata.usage.prompt_cache_miss_tokens == 4
    assert metadata.prompt_version == "zebra-deepseek-chat-v1"
    assert metadata.stable_prefix_hash is not None


def test_deepseek_stable_prefix_metadata_is_deterministic_for_tool_order() -> None:
    requests: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return _completion("done")

    gateway = _gateway(handle)
    first = gateway.complete(
        [_message("use tools")],
        tools=(_tool("zebra.last"), _tool("alpha.first")),
    )
    second = gateway.complete(
        [_message("use tools")],
        tools=(_tool("alpha.first"), _tool("zebra.last")),
    )

    assert [tool["function"]["name"] for tool in requests[0]["tools"]] == [
        "alpha__first",
        "zebra__last",
    ]
    assert first.call_metadata.tool_schema_bytes > 0
    assert first.call_metadata.tool_schema_hash == second.call_metadata.tool_schema_hash
    assert first.call_metadata.stable_prefix_hash == second.call_metadata.stable_prefix_hash


def test_deepseek_retries_retryable_error_only_before_public_delta() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return _completion("recovered")

    completion = _gateway(handle).complete([_message("retry")])

    assert calls == 2
    assert completion.call_metadata.retry_count == 1


@pytest.mark.parametrize(
    ("finish_reason", "normalized_error"),
    [
        ("length", "output_truncated"),
        ("content_filter", "content_filtered"),
    ],
)
def test_deepseek_rejects_incomplete_finish_reasons(
    finish_reason: str,
    normalized_error: str,
) -> None:
    with pytest.raises(ModelProviderError) as caught:
        _gateway(lambda request: _completion("partial", finish_reason=finish_reason)).complete(
            [_message("finish")]
        )

    assert caught.value.normalized_error == normalized_error


def test_deepseek_retries_insufficient_resources_before_public_output() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _completion(
                "not public yet",
                finish_reason="insufficient_system_resource",
            )
        return _completion("recovered")

    completion = _gateway(handle).complete([_message("retry resource")])

    assert calls == 2
    assert completion.call_metadata.retry_count == 1


def test_deepseek_stream_retries_before_first_public_delta() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"recovered"},'
            '"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    deltas = []
    completion = _gateway(handle).complete_stream(
        [_message("stream retry")],
        on_text_delta=deltas.append,
    )

    assert calls == 2
    assert [delta.content for delta in deltas] == ["recovered"]
    assert completion.call_metadata.retry_count == 1


def test_deepseek_does_not_retry_after_tool_side_effect() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    messages = [
        _message("run"),
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.TOOL,
            content="side effect completed",
            created_at=datetime(2026, 7, 17, tzinfo=UTC),
            tool_call_id="call-1",
        ),
    ]

    with pytest.raises(ModelProviderError) as caught:
        _gateway(handle).complete(messages)

    assert calls == 1
    assert caught.value.normalized_error == "provider_unavailable"
    assert caught.value.retry_count == 0


def test_deepseek_does_not_retry_after_public_stream_delta() -> None:
    calls = 0

    class FailingStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"visible"}}]}\n\n'
            raise httpx.ReadError("stream interrupted")

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=FailingStream())

    deltas = []
    with pytest.raises(ModelProviderError) as caught:
        _gateway(handle).complete_stream(
            [_message("stream")],
            on_text_delta=deltas.append,
        )

    assert calls == 1
    assert [delta.content for delta in deltas] == ["visible"]
    assert caught.value.retry_count == 0


def test_deepseek_stream_error_never_exposes_private_reasoning() -> None:
    gateway = OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-flash",
        max_retries=0,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text='data: {"error":{"reasoning_content":"private chain"}}\n\n',
                )
            )
        ),
    )

    with pytest.raises(ModelProviderError) as caught:
        gateway.complete_stream([_message("error")], on_text_delta=lambda delta: None)

    assert caught.value.normalized_error == "provider_stream_error"
    assert "private chain" not in str(caught.value)


def test_non_deepseek_openai_compatible_request_remains_legacy_shaped() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _completion("ok", model="custom-model")

    gateway = OpenAICompatibleModelGateway(
        provider_name="custom",
        base_url="https://example.test",
        api_key="secret",
        model_name="custom-model",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    gateway.complete([_message("hello")])

    assert captured == {
        "model": "custom-model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
    }


@pytest.mark.parametrize(
    ("status", "category", "retryable"),
    [
        (400, "invalid_request", False),
        (401, "authentication_failed", False),
        (402, "insufficient_balance", False),
        (422, "invalid_parameters", False),
        (429, "rate_limited", True),
        (500, "provider_error", True),
        (503, "provider_unavailable", True),
    ],
)
def test_deepseek_normalizes_http_errors(
    status: int,
    category: str,
    retryable: bool,
) -> None:
    gateway = OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret",
        model_name="deepseek-v4-flash",
        max_retries=0,
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, request=request))
        ),
    )

    with pytest.raises(ModelProviderError) as caught:
        gateway.complete([_message("classify error")])

    assert caught.value.normalized_error == category
    assert caught.value.retryable is retryable


def _gateway(handler) -> OpenAICompatibleModelGateway:
    return OpenAICompatibleModelGateway(
        provider_name="deepseek",
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
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
    )


def _tool(name: str = "files.read") -> ModelToolDefinition:
    return ModelToolDefinition(
        name=name,
        description="Read a file.",
        parameters={"type": "object", "properties": {}},
    )


def _completion(
    content: str,
    *,
    model: str = "deepseek-v4-flash",
    finish_reason: str = "stop",
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
        },
    )

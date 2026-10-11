"""An explicit empty private reasoning field is presence, not semantic output."""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelInvocationPolicy,
    ModelReasoningEffort,
    ModelThinkingMode,
    ModelToolDefinition,
)
from agent_core.harness.model_request import complete_model
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_integrations import openai_streaming
from agent_integrations.deepseek_profiles import DeepSeekProfileRouter
from agent_integrations.model_errors import ModelProviderError
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_integrations.openai_payloads import parse_completion, serialize_message

POLICY = ModelInvocationPolicy(
    profile_id="deepseek-v4-flash-executor-v1",
    thinking_mode=ModelThinkingMode.ENABLED,
    reasoning_effort=ModelReasoningEffort.HIGH,
)
TOOL = ModelToolDefinition(
    name="read", description="Read", parameters={"type": "object", "properties": {}}
)


def event(delta: dict[str, object], finish: str | None = None) -> bytes:
    return (
        "data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]}) + "\n\n"
    ).encode()


def tool_stream(reasoning: object = "", *, public: bool = True) -> bytes:
    delta: dict[str, object] = {
        "tool_calls": [
            {"index": 0, "id": "call-1", "function": {"name": "read", "arguments": "{}"}}
        ]
    }
    if reasoning != "missing":
        delta["reasoning_content"] = reasoning
    if public:
        delta["content"] = "I will read."
    return event(delta) + event({}, "tool_calls") + b"data: [DONE]\n\n"


def read(body: bytes, callback: Callable[[], None] | None = None) -> dict[str, Any]:
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    ) as client:
        return openai_streaming.read_openai_stream(
            client,
            url="https://example.test/chat",
            headers={},
            body={},
            on_text_delta=lambda delta: None,
            on_semantic_output=callback,
        )


def parse(payload: dict[str, Any]) -> ModelCompletion:
    return parse_completion(
        payload,
        provider_name="deepseek",
        default_model_name="deepseek-flash",
        latency_ms=1,
        resolved=DeepSeekProfileRouter().resolve(POLICY, has_tools=True),
        tools_advertised=True,
        internal_names={"read": "read"},
    )


def test_explicit_empty_reasoning_with_public_text_and_tool_roundtrips() -> None:
    payload = read(tool_stream())
    assert payload["choices"][0]["message"]["reasoning_content"] == ""
    completion = parse(payload)
    assert completion.assistant_message.provider_reasoning_content == ""
    serialized = serialize_message(completion.assistant_message, include_provider_reasoning=True)
    assert serialized["reasoning_content"] == ""
    assert serialized["content"] == "I will read."
    assert serialized["tool_calls"][0]["id"] == "call-1"


@pytest.mark.parametrize("reasoning", [None, "missing"])
def test_missing_or_null_reasoning_is_not_filled(reasoning: object) -> None:
    with pytest.raises(ModelResponseRejectedError) as caught:
        parse(read(tool_stream(reasoning)))
    assert caught.value.validation_rule == "reasoning_content_required"


def test_empty_only_without_terminal_remains_retryable() -> None:
    semantic = []
    with pytest.raises(ModelProviderError) as caught:
        read(event({"reasoning_content": ""}), lambda: semantic.append(True))
    assert caught.value.normalized_error == "provider_stream_terminal_missing"
    assert caught.value.retryable is True
    assert not semantic


def test_empty_only_deadline_remains_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    semantic: list[bool] = []
    monkeypatch.setattr(openai_streaming, "perf_counter", lambda: clock[0])

    class DeadlineStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield event({"reasoning_content": ""})
            clock[0] = 181.0
            yield b": heartbeat\n\n"

    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=DeadlineStream()))
    ) as client:
        with pytest.raises(ModelProviderError) as caught:
            openai_streaming.read_openai_stream(
                client,
                url="https://example.test/chat",
                headers={},
                body={},
                on_text_delta=lambda delta: None,
                on_semantic_output=lambda: semantic.append(True),
            )
    assert caught.value.normalized_error == "provider_stream_deadline_exceeded"
    assert caught.value.retryable is True
    assert not semantic


def test_nonempty_chunks_preserve_exact_text_and_single_empty_presence() -> None:
    parts: list[str] = []
    for value in ("", "", " leading", "", " trailing ", ""):
        openai_streaming._consume_choices(
            [{"delta": {"reasoning_content": value}}],
            content_parts=[],
            reasoning_parts=parts,
            tool_parts={},
            coalescer=openai_streaming._TextDeltaEmitter(lambda delta: None),
        )
    assert parts == ["", " leading", " trailing "]
    payload = read(
        event({"reasoning_content": ""})
        + event({"reasoning_content": " leading"})
        + tool_stream(" trailing ")
    )
    assert parse(payload).assistant_message.provider_reasoning_content == " leading trailing "


@pytest.mark.parametrize("recover", [True, False])
def test_malformed_after_empty_allows_exactly_one_harness_repair(recover: bool) -> None:
    calls = []
    malformed = event({"reasoning_content": ""}) + b"data: malformed\n\n"

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, content=tool_stream(public=False) if recover and len(calls) == 2 else malformed
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        gateway = OpenAICompatibleModelGateway(
            provider_name="deepseek",
            base_url="https://example.test",
            api_key="unused",
            model_name="deepseek-flash",
            client=client,
        )
        messages = [
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content="Read",
                created_at=datetime.now(UTC),
            )
        ]
        if recover:
            completion = complete_model(
                gateway,
                messages,
                (TOOL,),
                model_call_id="logical-call",
                on_delta=lambda call, delta: None,
                invocation_policy=POLICY,
            )
            assert completion.call_metadata.response_repair_count == 1
            assert completion.assistant_message.provider_reasoning_content == ""
        else:
            with pytest.raises(ModelResponseRejectedError) as caught:
                complete_model(
                    gateway,
                    messages,
                    (TOOL,),
                    model_call_id="logical-call",
                    on_delta=lambda call, delta: None,
                    invocation_policy=POLICY,
                )
            assert caught.value.response_repair_count == 1
        assert len(calls) == 2

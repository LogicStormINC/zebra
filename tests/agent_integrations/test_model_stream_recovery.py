import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCall
from agent_core.harness.model_request import complete_model
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_integrations import deepseek_responses_streaming, openai_streaming
from agent_integrations.deepseek_responses import DeepSeekResponsesModelGateway
from agent_integrations.model_errors import ModelProviderError
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway


def event(payload):
    return f"data: {json.dumps(payload)}\n\n".encode()


def delta(wire, kind):
    if wire == "responses":
        return event({
            "type": {
                "text": "response.output_text.delta",
                "reasoning": "response.reasoning_text.delta",
                "tool": "response.function_call_arguments.delta",
            }[kind],
            "sequence_number": 0,
            "delta": "piece",
        })
    return event({"choices": [{"delta": {
        "text": {"content": "piece"},
        "reasoning": {"reasoning_content": "piece"},
        "tool": {"tool_calls": [{
            "index": 0, "id": "call-1",
            "function": {"name": "read", "arguments": "{"},
        }]},
    }[kind]}]})


def success(wire):
    if wire == "responses":
        return delta(wire, "text") + event({
            "type": "response.completed", "sequence_number": 1,
            "response": {
                "id": "resp-1", "status": "completed", "model": "deepseek-v4-flash",
                "output": [{"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": "piece"},
                ]}],
            },
        })
    return delta(wire, "text") + event({
        "choices": [{"delta": {}, "finish_reason": "stop"}],
    }) + b"data: [DONE]\n\n"


class Stream(httpx.SyncByteStream):
    def __init__(self, chunks, failure=None, clock=None):
        self.chunks = chunks
        self.failure = failure
        self.clock = clock
        self.closed = False

    def __iter__(self):
        yield from self.chunks
        if self.clock is not None:
            self.clock[0] += 181
            yield b": heartbeat\n\n"
        if self.failure is not None:
            raise self.failure

    def close(self):
        self.closed = True


@pytest.fixture(params=["chat", "deepseek-chat", "responses"])
def wire(request):
    return request.param


def gateway(wire, client, retries=1):
    options = dict(
        base_url="https://example.com", api_key="secret",
        model_name="deepseek-v4-flash", client=client, max_retries=retries,
    )
    if wire == "responses":
        return DeepSeekResponsesModelGateway(**options)
    return OpenAICompatibleModelGateway(
        provider_name="deepseek" if wire == "deepseek-chat" else "openai", **options,
    )


@pytest.mark.parametrize("failure", ["deadline", "transport", "503"])
def test_empty_stream_recovers_once_same_request(wire, failure, monkeypatch):
    clock = [0.0]
    module = deepseek_responses_streaming if wire == "responses" else openai_streaming
    monkeypatch.setattr(module, "perf_counter", lambda: clock[0])
    requests = []
    streams = []

    def handle(request):
        requests.append(request.content)
        if len(requests) == 1:
            if failure == "503":
                return httpx.Response(503)
            stream = Stream(
                [b": heartbeat\n\n"],
                httpx.ReadTimeout("timeout") if failure == "transport" else None,
                clock if failure == "deadline" else None,
            )
        else:
            stream = Stream([success(wire)])
        streams.append(stream)
        return httpx.Response(200, stream=stream)

    deltas = []
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        completion = gateway(wire, client).complete_stream([], on_text_delta=deltas.append)
        assert not client.is_closed
    assert requests[0] == requests[1]
    assert len(requests) == 2
    assert completion.call_metadata.retry_count == 1
    assert completion.assistant_message.content == "piece"
    assert [(d.index, d.content) for d in deltas] == [(0, "piece")]
    assert all(stream.closed for stream in streams)


@pytest.mark.parametrize("retries", [0, 1, 2])
@pytest.mark.parametrize("failure", ["503", "deadline"])
def test_retry_budget_is_exact(wire, retries, failure, monkeypatch):
    calls = []
    clock = [0.0]
    module = deepseek_responses_streaming if wire == "responses" else openai_streaming
    monkeypatch.setattr(module, "perf_counter", lambda: clock[0])

    def handle(request):
        calls.append(request)
        if failure == "deadline":
            return httpx.Response(200, stream=Stream([], clock=clock))
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ModelProviderError) as caught:
            gateway(wire, client, retries).complete_stream([], on_text_delta=lambda _: None)
    assert len(calls) == retries + 1
    assert caught.value.retry_count == retries
    assert not caught.value.retryable


@pytest.mark.parametrize("kind", ["text", "reasoning", "tool"])
@pytest.mark.parametrize("failure", ["transport", "deadline", "malformed", "eof"])
def test_partial_stream_is_never_replayed(wire, kind, failure, monkeypatch):
    clock = [0.0]
    module = deepseek_responses_streaming if wire == "responses" else openai_streaming
    monkeypatch.setattr(module, "perf_counter", lambda: clock[0])
    calls = []
    chunks = [delta(wire, kind)]
    if failure == "malformed":
        chunks.append(b"data: {bad\n\n")
    stream = Stream(
        chunks, httpx.ReadError("reset") if failure == "transport" else None,
        clock if failure == "deadline" else None,
    )

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=stream)

    deltas = []
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises((ModelProviderError, ModelResponseRejectedError)) as caught:
            gateway(wire, client, 2).complete_stream([], on_text_delta=deltas.append)
    assert len(calls) == 1
    assert not caught.value.retryable
    assert [d.content for d in deltas] == (["piece"] if kind == "text" else [])
    assert stream.closed


def test_transport_retry_cannot_renew_budget_through_harness_repair(wire):
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"data: {bad\n\n")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ModelResponseRejectedError) as caught:
            complete_model(
                gateway(wire, client), [], (), model_call_id="call-1",
                on_delta=lambda *_: None,
            )
    assert len(calls) == 2
    assert not caught.value.retryable


@pytest.mark.parametrize("kind", ["reasoning", "tool", "text"])
def test_completed_invalid_response_repairs_only_unpublished_output(wire, kind):
    requests = []
    if wire == "responses":
        invalid = delta(wire, kind) + event({
            "type": "response.completed", "sequence_number": 1,
            "response": {"id": "bad", "status": "completed", "output": []},
        })
    else:
        # Invalid complete tool arguments, or reasoning without an answer.
        invalid = delta(wire, kind)
        if kind == "text":
            invalid += delta(wire, "tool")
        invalid += event({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        invalid += b"data: [DONE]\n\n"

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=invalid if len(requests) == 1 else success(wire))

    deltas = []
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        if kind == "text":
            with pytest.raises(ModelResponseRejectedError):
                complete_model(gateway(wire, client), [], (), model_call_id="repair",
                               on_delta=lambda _, delta: deltas.append(delta.content))
            assert len(requests) == 1
        else:
            result = complete_model(gateway(wire, client), [], (), model_call_id="repair",
                                    on_delta=lambda _, delta: deltas.append(delta.content))
            assert result.call_metadata.response_repair_count == 1
            assert len(requests) == 2
            if wire != "responses":
                assert "Internal model-response repair" in requests[1]["messages"][-1]["content"]
        assert deltas == ["piece"]


@pytest.mark.parametrize("streaming", [False, True])
def test_tool_history_is_reused_without_tool_execution(wire, streaming):
    calls = []
    execute_tool = Mock(return_value="already executed")
    now = datetime.now(UTC)
    call = ToolCall(
        tool_call_id=new_tool_call_id(), name="files.read", arguments={"path": "proof"},
        created_at=now, provider_call_id="call-1",
    )
    messages = [
        SessionMessage(
            message_id=new_message_id(), role=MessageRole.ASSISTANT,
            content="Tool calls proposed.", tool_calls=(call,), created_at=now,
        ),
        SessionMessage(
            message_id=new_message_id(), role=MessageRole.TOOL, content=execute_tool(),
            tool_call_id="call-1", created_at=now,
        ),
    ]
    execute_tool.reset_mock()

    def handle(request):
        calls.append(request.content)
        if len(calls) == 1:
            # The already serialized request must not be rebuilt from changed history.
            messages.append(SessionMessage(
                message_id=new_message_id(), role=MessageRole.USER,
                content="later input must not enter retry", created_at=now,
            ))
            raise httpx.ReadTimeout("timeout")
        if streaming:
            return httpx.Response(200, content=success(wire))
        if wire == "responses":
            payload = json.loads(success(wire).split(b"data: ")[-1])["response"]
        else:
            payload = {"choices": [{
                "message": {"role": "assistant", "content": "piece"},
                "finish_reason": "stop",
            }]}
        return httpx.Response(200, json=payload)

    tools = (ModelToolDefinition(
        name="files.read", description="Read",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
    ),)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter = gateway(wire, client)
        completion = (
            adapter.complete_stream(messages, tools=tools, on_text_delta=lambda _: None)
            if streaming else adapter.complete(messages, tools=tools)
        )
    assert len(calls) == 2
    assert calls[0] == calls[1]
    body = json.loads(calls[1])
    assert all(tool["type"] == "function" for tool in body["tools"])
    history = body["input" if wire == "responses" else "messages"]
    result = history[-1]
    assert result["output" if wire == "responses" else "content"] == "already executed"
    assert result["call_id" if wire == "responses" else "tool_call_id"] == "call-1"
    assert completion.call_metadata.retry_count == 1
    assert not completion.tool_calls
    execute_tool.assert_not_called()


@pytest.mark.parametrize("malformed", [False, True])
def test_nonstream_recovery_budget_and_repair_safety(wire, malformed):
    calls = []

    def handle(request):
        calls.append(request)
        if malformed and len(calls) > 1:
            return httpx.Response(200, content=b"{bad")
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises((ModelProviderError, ModelResponseRejectedError)) as caught:
            gateway(wire, client, 2).complete([])
    assert len(calls) == (2 if malformed else 3)
    if malformed:
        assert not caught.value.retryable
    else:
        assert caught.value.retry_count == 2
        assert not caught.value.retryable


@pytest.mark.parametrize("source", ["reader", "callback"])
def test_cancellation_propagates_without_retry(wire, source):
    cancellation = asyncio.CancelledError()
    stream = Stream(
        [delta(wire, "text")] if source == "callback" else [],
        cancellation if source == "reader" else None,
    )
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=stream)

    def cancel(_):
        raise cancellation

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(asyncio.CancelledError) as caught:
            gateway(wire, client).complete_stream([], on_text_delta=cancel)
    assert caught.value is cancellation
    assert len(calls) == 1
    assert stream.closed

import asyncio
import gzip
import json
import socket
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic

import httpx
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_session_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelInvocationPolicy,
    ModelRole,
    ModelThinkingMode,
    ModelToolChoice,
)
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_integrations.ag_ui import AgUiProjector, AgUiRunIdentity
from agent_integrations.bounded_model_http import post_bounded_json, validate_bounded_policy
from agent_integrations.deepseek_responses import DeepSeekResponsesModelGateway
from agent_integrations.model_errors import ModelProviderError
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_integrations.openai_streaming import read_openai_stream


def _policy() -> ModelInvocationPolicy:
    return ModelInvocationPolicy(
        role=ModelRole.SUMMARIZER,
        thinking_mode=ModelThinkingMode.DISABLED,
        tool_choice=ModelToolChoice.NONE,
        max_output_tokens=128,
    )


def _message() -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        created_at=datetime.now(UTC),
        content="Confirmed count: 2 of 20.",
    )


def _gateway(kind: str, *, client=None, base_url="https://example.com"):
    options = dict(
        base_url=base_url,
        api_key="test",
        model_name="deepseek-flash",
        max_retries=3,
        client=client,
    )
    if kind == "responses":
        return DeepSeekResponsesModelGateway(**options)
    return OpenAICompatibleModelGateway(provider_name="deepseek", **options)


def _mock_aux_http(monkeypatch, respond: Callable[[httpx.Request], httpx.Response]) -> None:
    async_client = httpx.AsyncClient

    async def handle(request: httpx.Request) -> httpx.Response:
        return respond(request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle), **kwargs),
    )


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_bounded_provider_request_is_small_no_tools_no_reasoning_no_retries(
    monkeypatch,
    kind: str,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request):
        requests.append(request)
        return httpx.Response(503)

    _mock_aux_http(monkeypatch, respond)
    with pytest.raises(ModelProviderError) as failure:
        _gateway(kind).complete([_message()], invocation_policy=_policy(), deadline_s=1)
    assert not failure.value.retryable and failure.value.retry_count == 0
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert "tools" not in body and "reasoning_effort" not in body
    if kind == "chat":
        assert body["thinking"] == {"type": "disabled"}
        assert body["tool_choice"] == "none" and body["max_tokens"] == 128
    else:
        assert body["reasoning"] == {"effort": "none"}
        assert body["max_output_tokens"] == 128
    assert requests[0].headers["accept-encoding"] == "identity"
    assert all(value == 1 for value in requests[0].extensions["timeout"].values())


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_injected_sync_transport_fails_closed_without_io_or_settings_changes(kind: str) -> None:
    requests: list[httpx.Request] = []

    def respond(request):
        requests.append(request)
        return httpx.Response(503)

    with httpx.Client(
        transport=httpx.MockTransport(respond),
        timeout=17,
        headers={"Accept-Encoding": "gzip", "X-Main": "preserved"},
        trust_env=False,
    ) as client:
        gateway = _gateway(kind, client=client)
        with pytest.raises(ValueError, match="synchronous client"):
            gateway.complete([_message()], invocation_policy=_policy(), deadline_s=1)
        assert requests == [] and not client.is_closed
        # Main calls still use the injected transport, its headers and timeout, and retry.
        with pytest.raises(ModelProviderError) as failure:
            gateway.complete([_message()])
        assert failure.value.retry_count == 3
        assert len(requests) == 4
        assert requests[0].headers["accept-encoding"] == "gzip"
        assert requests[0].headers["x-main"] == "preserved"
        assert all(value == 17 for value in requests[0].extensions["timeout"].values())


@pytest.mark.parametrize("tokens", [1, 128, 129, 256])
def test_bounded_policy_has_approved_128_token_ceiling(tokens: int) -> None:
    policy = replace(_policy(), max_output_tokens=tokens)
    if tokens <= 128:
        assert validate_bounded_policy(policy, has_tools=False) == tokens
    else:
        with pytest.raises(ValueError):
            validate_bounded_policy(policy, has_tools=False)


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("tokens", [129, 256])
def test_oversized_token_policy_is_rejected_before_any_http(monkeypatch, kind, tokens) -> None:
    def forbidden_client(**kwargs):
        pytest.fail("invalid auxiliary policy must not create an HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden_client)
    with pytest.raises(ValueError):
        _gateway(kind).complete(
            [_message()],
            invocation_policy=replace(_policy(), max_output_tokens=tokens),
            deadline_s=1,
        )


@pytest.mark.parametrize("deadline", [0, -1, 2.01, 5, float("nan"), float("inf")])
def test_auxiliary_deadline_cannot_exceed_two_seconds(deadline: float) -> None:
    with pytest.raises(ValueError, match="deadline"):
        post_bounded_json(None, "https://example.com", {}, {}, deadline_s=deadline)


class _AsyncReceipt(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...], *, delay_s: float = 0) -> None:
        self.chunks = chunks
        self.delay_s = delay_s
        self.reads = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            await asyncio.sleep(self.delay_s)
            self.reads += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _completion_payload(kind: str, text: str) -> dict:
    if kind == "chat":
        return {
            "choices": [
                {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            ]
        }
    return {
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
    }


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_bounded_completion_parses_success_and_closes_owned_client(monkeypatch, kind) -> None:
    text = '{"order":[0],"lead":"none"}'
    stream = _AsyncReceipt((json.dumps(_completion_payload(kind, text)).encode(),))
    clients = []
    async_client = httpx.AsyncClient

    async def respond(request):
        return httpx.Response(200, stream=stream)

    def create_client(**kwargs):
        # AUX keeps httpx's native proxy/TLS defaults; only timeout is explicit.
        assert set(kwargs) == {"timeout"}
        client = async_client(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", create_client)
    completion = _gateway(kind).complete(
        [_message()],
        invocation_policy=_policy(),
        deadline_s=1,
    )
    assert completion.assistant_message.content == text and completion.tool_calls == ()
    assert completion.call_metadata.retry_count == 0
    assert stream.closed and len(clients) == 1 and clients[0].is_closed


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("content", [b"{}", b"["])
def test_auxiliary_invalid_payload_is_not_retryable(monkeypatch, kind, content) -> None:
    stream = _AsyncReceipt((content,))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, stream=stream)

    _mock_aux_http(monkeypatch, respond)
    with pytest.raises((ValueError, ModelResponseRejectedError)) as failure:
        _gateway(kind).complete([_message()], invocation_policy=_policy(), deadline_s=1)
    if isinstance(failure.value, ModelResponseRejectedError):
        assert not failure.value.retryable
    assert len(requests) == 1 and stream.closed


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_main_model_keeps_large_compressed_response_support(kind) -> None:
    text = "x" * 32769
    encoded = json.dumps(_completion_payload(kind, text)).encode()
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            content=gzip.compress(encoded),
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        completion = _gateway(kind, client=client).complete([_message()])
        assert not client.is_closed
    assert completion.assistant_message.content == text
    assert len(requests) == 1 and requests[0].headers["accept-encoding"] != "identity"


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "identity, gzip"])
def test_compressed_receipt_is_rejected_before_body_read_or_decompression(
    monkeypatch,
    kind: str,
    encoding: str,
) -> None:
    compressed = gzip.compress(b"x" * (8 * 1024 * 1024))
    assert len(compressed) < 32768
    stream = _AsyncReceipt((compressed,))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"Content-Encoding": encoding}, stream=stream)

    def forbid_decoder(*_):
        pytest.fail("auxiliary receipt must never construct a content decoder")

    _mock_aux_http(monkeypatch, respond)
    monkeypatch.setattr(httpx.Response, "_get_content_decoder", forbid_decoder)
    with pytest.raises(ValueError, match="encoding"):
        _gateway(kind).complete([_message()], invocation_policy=_policy(), deadline_s=1)
    assert len(requests) == 1 and stream.reads == 0 and stream.closed


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("declared_length", [None, "32769"])
def test_auxiliary_raw_overflow_closes_receipt_and_never_retries(
    monkeypatch,
    kind: str,
    declared_length: str | None,
) -> None:
    stream = _AsyncReceipt((b"x" * 32768, b"x", b"not read"))
    requests = []

    def respond(request):
        requests.append(request)
        headers = {} if declared_length is None else {"Content-Length": declared_length}
        return httpx.Response(200, headers=headers, stream=stream)

    _mock_aux_http(monkeypatch, respond)
    with pytest.raises(ValueError, match="size bound"):
        _gateway(kind).complete([_message()], invocation_policy=_policy(), deadline_s=1)
    assert len(requests) == 1 and stream.closed
    assert stream.reads == (2 if declared_length is None else 0)


def test_exact_raw_limit_and_identity_encoding_are_accepted(monkeypatch) -> None:
    encoded = b'{"value":"' + b"x" * (32768 - 12) + b'"}'
    assert len(encoded) == 32768
    stream = _AsyncReceipt((encoded[:123], encoded[123:]))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"Content-Encoding": " Identity ", "Content-Length": "32768"},
            stream=stream,
        )

    _mock_aux_http(monkeypatch, respond)
    result = post_bounded_json(
        None,
        "https://example.com",
        {"accept-encoding": "gzip"},
        {},
        deadline_s=2,
    )
    assert len(result["value"]) == 32768 - 12
    assert requests[0].headers.get_list("accept-encoding") == ["identity"]
    assert stream.closed


def test_trickling_body_is_cancelled_at_total_deadline_and_closed(monkeypatch) -> None:
    stream = _AsyncReceipt((b" ",) * 100, delay_s=0.01)
    _mock_aux_http(monkeypatch, lambda _: httpx.Response(200, stream=stream))
    started = monotonic()
    with pytest.raises(TimeoutError):
        post_bounded_json(None, "https://example.com", {}, {}, deadline_s=0.15)
    assert monotonic() - started < 0.5
    assert 0 < stream.reads < 100 and stream.closed


def test_threaded_dns_fails_closed_without_starting_resolver_threads(monkeypatch) -> None:
    # Do not depend on the developer's proxy environment for a direct-DNS test.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv("NO_PROXY", "*")

    def forbidden_dns(*args, **kwargs):
        pytest.fail("uncancellable getaddrinfo must not run in the background")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden_dns)
    threads = set(threading.enumerate())
    with pytest.raises(ValueError, match="threaded"):
        post_bounded_json(None, "http://example.invalid", {}, {}, deadline_s=0.2)
    assert set(threading.enumerate()) == threads


def test_auxiliary_call_inside_running_loop_fails_closed(monkeypatch) -> None:
    def forbidden_client(**kwargs):
        pytest.fail("nested synchronous call must fail before creating an HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden_client)

    async def call():
        with pytest.raises(ValueError, match="running event loop"):
            post_bounded_json(None, "https://example.com", {}, {}, deadline_s=1)

    asyncio.run(call())


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("use_proxy", [False, True])
def test_real_trickling_headers_obey_total_deadline_without_orphan_io(
    monkeypatch,
    kind: str,
    use_proxy: bool,
) -> None:
    stop = threading.Event()
    requests: list[bytes] = []
    disconnected = threading.Event()
    errors: list[Exception] = []

    def serve(listener: socket.socket) -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(1)
                request = b""
                while b"\r\n\r\n" not in request:
                    request += connection.recv(4096)
                requests.append(request)
                connection.sendall(b"HTTP/1.1 200 OK\r\nX-Trickle: ")
                connection.setblocking(False)
                # This is faster than the per-read timeout, but headers never finish.
                for _ in range(100):
                    if stop.wait(0.01):
                        return
                    connection.sendall(b"x")
                    try:
                        if connection.recv(4096, socket.MSG_PEEK) == b"":
                            disconnected.set()
                            return
                    except BlockingIOError:
                        pass
                connection.sendall(b"\r\nContent-Length: 2\r\n\r\n{}")
        except (BrokenPipeError, ConnectionResetError):
            disconnected.set()
        except Exception as exc:
            errors.append(exc)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(1)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            monkeypatch.delenv(name, raising=False)
            monkeypatch.delenv(name.lower(), raising=False)
        if use_proxy:
            monkeypatch.setenv("HTTP_PROXY", url)
            url = "http://model.example.invalid"
        original_threads = set(threading.enumerate())
        server = threading.Thread(target=serve, args=(listener,))
        server.start()
        try:
            started = monotonic()
            with pytest.raises(ModelProviderError) as failure:
                _gateway(kind, base_url=url).complete(
                    [_message()],
                    invocation_policy=_policy(),
                    deadline_s=0.3,
                )
            assert not failure.value.retryable and failure.value.retry_count == 0
            assert monotonic() - started < 0.6
            assert disconnected.wait(0.2), "deadline must close the live socket"
        finally:
            stop.set()
            server.join(timeout=1.2)
        assert not server.is_alive() and errors == []
        assert len(requests) == 1
        assert b"Accept-Encoding: identity" in requests[0]
        if use_proxy:
            assert b"POST http://model.example.invalid/" in requests[0]
        assert set(threading.enumerate()) == original_threads


def test_upstream_provider_does_not_hide_short_text_before_next_chunk() -> None:
    deltas = []

    class PausedStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
            assert [delta.content for delta in deltas] == ["first"]
            yield b'data: {"choices":[{"delta":{"content":"second"}}]}\n\n'
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'

    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=PausedStream()))
    ) as client:
        read_openai_stream(
            client, url="https://example.com", headers={}, body={}, on_text_delta=deltas.append
        )
    assert [delta.content for delta in deltas] == ["first", "second"]


def test_auxiliary_receipt_projects_usage_only_never_display_json() -> None:
    session_id = new_session_id()
    event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        created_at=datetime.now(UTC),
        payload={
            "assistant_message": '{"order":[0,1],"lead":"none"}',
            "response_stage": "public_expression",
            "role": "summarizer",
            "model_call_id": "expression:1",
            "input_tokens": 20,
            "output_tokens": 12,
        },
    )
    events = (
        AgUiProjector()
        .project([event], AgUiRunIdentity(session_id=session_id, thread_id="task", run_id="run"))
        .events
    )
    assert [item.type.value for item in events] == ["RUN_STARTED", "CUSTOM"]
    assert events[-1].name == "zebra.model_usage"
    assert events[-1].value["response_stage"] == "public_expression"
    assert events[-1].value["output_tokens"] == 12

"""Ordinary guarded transport; no estimate can replace a trusted tokenizer contract."""

import asyncio
import json
import threading
from collections.abc import Callable
from hashlib import sha256
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx
from agent_core.domain.modeling import ModelCompletion, ModelTextDelta
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_core.ports.worker_budget import (
    ModelRequestBudget,
    ModelRequestOutcomeUnknown,
    WorkerBudgetError,
)

from agent_integrations.bounded_model_dns import model_io_loop

# CA-HA-03 D7: cache the event loop + AsyncClient across model calls.
# Each guarded_completion previously paid ~500-800ms for asyncio.Runner
# creation + httpx.AsyncClient construction (SSL context, connection pool,
# DNS resolver). A worker-level singleton amortizes this to once per process.
_LOOP_LOCK = threading.Lock()
_CACHED_LOOP: asyncio.AbstractEventLoop | None = None
_CACHED_CLIENT: httpx.AsyncClient | None = None


def _get_model_transport() -> tuple[asyncio.AbstractEventLoop, httpx.AsyncClient | None]:
    """Return (loop, cached_client_or_None); caller must not close either."""
    global _CACHED_LOOP, _CACHED_CLIENT
    with _LOOP_LOCK:
        if _CACHED_LOOP is None or _CACHED_LOOP.is_closed():
            _CACHED_LOOP = model_io_loop()
            _CACHED_CLIENT = None  # new loop invalidates cached client
        if _CACHED_CLIENT is None:
            _CACHED_CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                follow_redirects=False,
                trust_env=False,
            )
        return _CACHED_LOOP, _CACHED_CLIENT


def _reset_model_transport() -> None:
    """Force re-creation on next call (for tests)."""
    global _CACHED_LOOP, _CACHED_CLIENT
    with _LOOP_LOCK:
        if _CACHED_LOOP is not None and not _CACHED_LOOP.is_closed():
            _CACHED_LOOP.close()
        _CACHED_LOOP = None
        _CACHED_CLIENT = None


def inspect_request(gateway: Any, body: dict[str, Any]) -> ModelRequestBudget:
    injected = gateway._client
    if injected is not None and not isinstance(injected._transport, httpx.MockTransport):
        raise WorkerBudgetError("model custom synchronous transport is not cancellable")
    _supported_content(body)
    counter = getattr(gateway, "model_request_budget", None)
    if not callable(counter):
        raise WorkerBudgetError("trusted exact-request model counter is unavailable")
    exact = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(exact) > 4 * 1024 * 1024:
        raise WorkerBudgetError("model request exceeds bounded wire size")
    request = counter(exact)
    if (
        not isinstance(request, ModelRequestBudget)
        or request.exact_body != exact
        or request.request_digest != sha256(exact).hexdigest()
    ):
        raise WorkerBudgetError("counter inspected different wire bytes")
    cap = body.get("max_tokens", body.get("max_output_tokens"))
    if type(cap) is not int or cap != request.output_cap:
        raise WorkerBudgetError("counter output cap differs from actual provider request")
    # Counter must explicitly reject unsupported image/continuation encodings itself.
    return request


def _supported_content(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("type") in ("image_url", "input_image", "image", "file", "input_file") or any(
            key in value for key in ("previous_response_id", "continuation")
        ):
            raise WorkerBudgetError("guarded counter contract does not support image/continuation")
        for child in value.values():
            _supported_content(child)
    elif isinstance(value, list):
        for child in value:
            _supported_content(child)


def guarded_completion(
    gateway: Any,
    body: dict[str, Any],
    parse: Callable[[dict[str, Any]], ModelCompletion],
    *,
    stream_sink: Callable[[ModelTextDelta], None] | None = None,
    responses: bool = False,
) -> ModelCompletion:
    gate = gateway.worker_budget
    if gateway.authority_check is not None:
        gateway.authority_check(uuid4().hex)
    request = inspect_request(gateway, body)
    reservation = gate.before_model(request)  # independent COMMIT before opening any socket
    remaining = gate.check()
    started = monotonic()
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise WorkerBudgetError("synchronous guarded transport cannot block an async loop")
    # Existing native async cancellation scope bounds connect, body and cleanup together.
    # CA-HA-03 D7: reuse the cached loop + client instead of per-call creation.
    try:
        loop, cached_client = _get_model_transport()
        if cached_client is not None:
            gateway._wire_client = cached_client  # _wire picks this up
        payload = loop.run_until_complete(
            _wire(gateway, request.exact_body, remaining, stream_sink, responses)
        )
        gateway._wire_client = None  # clear reference; not part of gateway state
        gateway._wire_buffer = None
    except (httpx.TransportError, TimeoutError) as error:
        _reset_model_transport()  # broken connection → recreate on next call
        raise ModelRequestOutcomeUnknown("model request outcome is unknown") from error
    if monotonic() - started >= remaining:
        raise ModelRequestOutcomeUnknown("model request outcome is unknown after its deadline")
    gate.check()
    try:
        completion = parse(payload)
    except ModelResponseRejectedError as error:
        error.retryable = False
        raise
    gate.after_model(reservation, payload)
    return completion


async def _wire(
    gateway: Any,
    exact: bytes,
    seconds: float,
    sink: Callable[[ModelTextDelta], None] | None,
    responses: bool,
) -> dict[str, Any]:
    injected = gateway._client
    transport = None
    if injected is not None:
        # Only the explicitly in-memory fixture transport implements both async/sync I/O.
        transport = injected._transport
        if not isinstance(transport, httpx.MockTransport):
            raise WorkerBudgetError("guarded transport requires cancellable native async I/O")
    url = gateway._base_url + ("/responses" if responses else "/chat/completions")
    cached = getattr(gateway, "_wire_client", None)
    async with asyncio.timeout(seconds):
        if cached is not None and transport is None:
            # D7: reuse the worker-level cached client (loop-bound, no cleanup).
            client = cached
            async with client.stream(
                "POST", url, headers=gateway._headers(), content=exact
            ) as response:
                await _drain_response(gateway, response, sink, responses)
                return _finalize_response(gateway, sink, responses, url)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(seconds),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream(
                "POST", url, headers=gateway._headers(), content=exact
            ) as response:
                await _drain_response(gateway, response, sink, responses)
                return _finalize_response(gateway, sink, responses, url)
    raise WorkerBudgetError("unreachable")  # pragma: no cover


async def _drain_response(
    gateway: Any,
    response: httpx.Response,
    sink: Callable[[ModelTextDelta], None] | None,
    responses: bool,
) -> None:
    """Stream the model response into gateway._wire_buffer."""
    content = bytearray()
    delta_index = 0
    response.raise_for_status()
    if sink is None:
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > 4 * 1024 * 1024:
                raise WorkerBudgetError("model response exceeds bounded body size")
            content.extend(chunk)
    else:
        async for line in response.aiter_lines():
            encoded = (line + "\n").encode()
            if len(content) + len(encoded) > 4 * 1024 * 1024:
                raise WorkerBudgetError("model stream exceeds bounded body size")
            content.extend(encoded)
            gateway.worker_budget.check()
            if line.startswith("data:") and line[5:].strip() != "[DONE]":
                event = json.loads(line[5:].strip())
                text = _public_delta(event, responses)
                if text:
                    sink(ModelTextDelta(index=delta_index, content=text))
                    delta_index += 1
    gateway._wire_buffer = bytes(content)


def _finalize_response(
    gateway: Any,
    sink: Callable[[ModelTextDelta], None] | None,
    responses: bool,
    url: str,
) -> dict[str, Any]:
    """Parse the buffered response; shared by cached and fresh-client paths."""
    content = gateway._wire_buffer
    gateway._wire_buffer = None
    if sink is None:
        result = json.loads(content)
        if not isinstance(result, dict):
            raise WorkerBudgetError("provider response must be an object")
        return result
    if not responses and not any(
            line.startswith(b"data:") and line[5:].strip() == b"[DONE]"
            for line in content.splitlines()):
        raise WorkerBudgetError("interrupted Chat stream leaves usage unknown")
    # Reuse the normal protocol's complete terminal/tool parser on the exact buffered SSE.
    from agent_integrations.deepseek_responses_streaming import read_deepseek_responses_stream
    from agent_integrations.openai_streaming import read_openai_stream

    reader = read_deepseek_responses_stream if responses else read_openai_stream
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=bytes(content)))
    ) as replay:
        return reader(replay, url=url, headers={}, body={}, on_text_delta=lambda _: None)


def _public_delta(event: Any, responses: bool) -> str:
    if not isinstance(event, dict):
        raise WorkerBudgetError("invalid stream event")
    if responses:
        text = event.get("delta") if event.get("type") == "response.output_text.delta" else None
    else:
        choices = event.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        delta = first.get("delta") if isinstance(first, dict) else None
        text = delta.get("content") if isinstance(delta, dict) else None
    if text is not None and not isinstance(text, str):
        raise WorkerBudgetError("invalid stream text")
    return text or ""


def guarded_chat(
    gateway: Any,
    body: dict[str, Any],
    *,
    tools: Any,
    tool_names: Any,
    resolved: Any,
    metadata: Any,
    sink: Any = None,
) -> ModelCompletion:
    from agent_integrations.openai_payloads import internal_tool_names, parse_completion

    if sink is not None:
        body["stream_options"] = {"include_usage": True}

    return guarded_completion(
        gateway,
        body,
        lambda payload: parse_completion(
            payload,
            provider_name=gateway._provider_name,
            default_model_name=gateway._model_name,
            latency_ms=0,
            retry_count=0,
            resolved=resolved,
            request_metadata=metadata,
            internal_names=internal_tool_names(tools, tool_names),
            tools_advertised=bool(tools),
        ),
        stream_sink=sink,
    )


def guarded_responses(
    gateway: Any,
    body: dict[str, Any],
    *,
    tools: Any,
    tool_names: Any,
    resolved: Any,
    metadata: Any,
    sink: Any = None,
) -> ModelCompletion:
    from agent_integrations.deepseek_responses_parse import parse_responses_completion
    from agent_integrations.openai_payloads import internal_tool_names

    return guarded_completion(
        gateway,
        body,
        lambda payload: parse_responses_completion(
            payload,
            resolved=resolved,
            request_metadata=metadata,
            internal_names=internal_tool_names(tools, tool_names),
            tools_advertised=bool(tools),
            latency_ms=0,
            retry_count=0,
        ),
        stream_sink=sink,
        responses=True,
    )

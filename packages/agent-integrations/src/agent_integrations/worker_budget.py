"""Ordinary guarded transport; no estimate can replace a trusted tokenizer contract."""

import asyncio
import json
from collections.abc import Callable
from hashlib import sha256
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx
from agent_core.domain.modeling import ModelCompletion, ModelTextDelta
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_core.ports.worker_budget import ModelRequestBudget, WorkerBudgetError

from agent_integrations.bounded_model_http import _bounded_loop


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
        kind = value.get("type")
        if (
            isinstance(kind, str)
            and kind in {"image_url", "input_image", "image", "file", "input_file"}
        ) or any(key in value for key in ("previous_response_id", "continuation")):
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
    with asyncio.Runner(loop_factory=_bounded_loop) as runner:
        payload = runner.run(_wire(gateway, request.exact_body, remaining, stream_sink, responses))
    if monotonic() - started >= remaining:
        raise WorkerBudgetError("model Task deadline exceeded")
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
    content = bytearray()
    delta_index = 0
    async with asyncio.timeout(seconds):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(seconds),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream(
                "POST", url, headers=gateway._headers(), content=exact
            ) as response:
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

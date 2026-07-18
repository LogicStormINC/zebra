from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx
from agent_core.domain.modeling import ModelTextDelta

from agent_integrations.model_errors import ModelProviderError

_COALESCE_CHARS = 64
_COALESCE_SECONDS = 0.05


@dataclass
class _ToolCallParts:
    call_id: str = ""
    name: str = ""
    arguments: str = ""


class _TextDeltaCoalescer:
    def __init__(self, sink: Callable[[ModelTextDelta], None]) -> None:
        self._sink = sink
        self._buffer = ""
        self._index = 0
        self._last_emit = perf_counter()

    def push(self, content: str) -> None:
        if not content:
            return
        if self._index == 0 and not self._buffer:
            self._emit(content)
            return
        self._buffer += content
        if (
            len(self._buffer) >= _COALESCE_CHARS
            or perf_counter() - self._last_emit >= _COALESCE_SECONDS
        ):
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        content, self._buffer = self._buffer, ""
        self._emit(content)

    def _emit(self, content: str) -> None:
        self._sink(ModelTextDelta(index=self._index, content=content))
        self._index += 1
        self._last_emit = perf_counter()


def read_openai_stream(
    client: httpx.Client,
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    on_text_delta: Callable[[ModelTextDelta], None],
) -> dict[str, Any]:
    started = perf_counter()
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_parts: dict[int, _ToolCallParts] = {}
    model_name: str | None = None
    usage: dict[str, Any] | None = None
    model_call_id: str | None = None
    system_fingerprint: str | None = None
    finish_reason: str | None = None
    first_event_ms: int | None = None
    first_public_text_ms: int | None = None
    coalescer = _TextDeltaCoalescer(on_text_delta)
    with client.stream("POST", url, headers=headers, json=body) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            raw = line.removeprefix("data:").strip()
            if not raw or raw == "[DONE]":
                continue
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("model stream event must be a JSON object")
            if "error" in payload:
                raise ModelProviderError("provider_stream_error", retryable=True)
            elapsed_ms = int((perf_counter() - started) * 1000)
            if first_event_ms is None:
                first_event_ms = elapsed_ms
            current_id = payload.get("id")
            if isinstance(current_id, str) and current_id.strip():
                model_call_id = current_id.strip()
            current_model = payload.get("model")
            if isinstance(current_model, str) and current_model.strip():
                model_name = current_model
            current_fingerprint = payload.get("system_fingerprint")
            if isinstance(current_fingerprint, str) and current_fingerprint.strip():
                system_fingerprint = current_fingerprint.strip()
            current_usage = payload.get("usage")
            if isinstance(current_usage, dict):
                usage = dict(current_usage)
            choice_finish_reason, emitted_public_text = _consume_choices(
                payload.get("choices"),
                content_parts=content_parts,
                reasoning_parts=reasoning_parts,
                tool_parts=tool_parts,
                coalescer=coalescer,
            )
            if choice_finish_reason is not None:
                finish_reason = choice_finish_reason
            if emitted_public_text and first_public_text_ms is None:
                first_public_text_ms = elapsed_ms
    coalescer.flush()
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content_parts) or None,
    }
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)
    if tool_parts:
        message["tool_calls"] = [
            {
                "id": parts.call_id,
                "type": "function",
                "function": {
                    "name": parts.name,
                    "arguments": parts.arguments,
                },
            }
            for _, parts in sorted(tool_parts.items())
        ]
    result: dict[str, Any] = {"choices": [{"message": message, "finish_reason": finish_reason}]}
    if model_call_id is not None:
        result["id"] = model_call_id
    if model_name is not None:
        result["model"] = model_name
    if usage is not None:
        result["usage"] = usage
    if system_fingerprint is not None:
        result["system_fingerprint"] = system_fingerprint
    result["_zebra_time_to_first_event_ms"] = first_event_ms
    result["_zebra_time_to_first_public_text_ms"] = first_public_text_ms
    return result


def _consume_choices(
    value: object,
    *,
    content_parts: list[str],
    reasoning_parts: list[str],
    tool_parts: dict[int, _ToolCallParts],
    coalescer: _TextDeltaCoalescer,
) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, list):
        raise ValueError("model stream choices must be a list")
    finish_reason: str | None = None
    emitted_public_text = False
    for choice in value:
        if not isinstance(choice, dict):
            raise ValueError("model stream choice must be an object")
        current_finish_reason = choice.get("finish_reason")
        if current_finish_reason is not None:
            if not isinstance(current_finish_reason, str):
                raise ValueError("model stream finish_reason must be a string")
            finish_reason = current_finish_reason
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("model stream content delta must be a string")
        if content:
            content_parts.append(content)
            coalescer.push(content)
            emitted_public_text = True
        reasoning_content = delta.get("reasoning_content")
        if reasoning_content is not None and not isinstance(reasoning_content, str):
            raise ValueError("model stream reasoning_content delta must be a string")
        if reasoning_content:
            reasoning_parts.append(reasoning_content)
        _consume_tool_calls(delta.get("tool_calls"), tool_parts)
    return finish_reason, emitted_public_text


def _consume_tool_calls(
    value: object,
    tool_parts: dict[int, _ToolCallParts],
) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError("model stream tool_calls must be a list")
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("model stream tool call delta must be an object")
        index = item.get("index")
        if not isinstance(index, int) or index < 0:
            raise ValueError("model stream tool call index must be non-negative")
        parts = tool_parts.setdefault(index, _ToolCallParts())
        call_id = item.get("id")
        if isinstance(call_id, str) and call_id:
            parts.call_id = call_id
        function = item.get("function")
        if function is None:
            continue
        if not isinstance(function, dict):
            raise ValueError("model stream tool call function must be an object")
        name = function.get("name")
        arguments = function.get("arguments")
        if isinstance(name, str):
            parts.name += name
        elif name is not None:
            raise ValueError("model stream tool call name must be a string")
        if isinstance(arguments, str):
            parts.arguments += arguments
        elif arguments is not None:
            raise ValueError("model stream tool call arguments must be a string")

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx
from agent_core.domain.modeling import ModelTextDelta

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
    content_parts: list[str] = []
    tool_parts: dict[int, _ToolCallParts] = {}
    model_name: str | None = None
    usage: dict[str, Any] | None = None
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
                raise ValueError(f"model stream failed: {payload['error']}")
            current_model = payload.get("model")
            if isinstance(current_model, str) and current_model.strip():
                model_name = current_model
            current_usage = payload.get("usage")
            if isinstance(current_usage, dict):
                usage = dict(current_usage)
            _consume_choices(
                payload.get("choices"),
                content_parts=content_parts,
                tool_parts=tool_parts,
                coalescer=coalescer,
            )
    coalescer.flush()
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content_parts) or None,
    }
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
    result: dict[str, Any] = {"choices": [{"message": message}]}
    if model_name is not None:
        result["model"] = model_name
    if usage is not None:
        result["usage"] = usage
    return result


def _consume_choices(
    value: object,
    *,
    content_parts: list[str],
    tool_parts: dict[int, _ToolCallParts],
    coalescer: _TextDeltaCoalescer,
) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError("model stream choices must be a list")
    for choice in value:
        if not isinstance(choice, dict):
            raise ValueError("model stream choice must be an object")
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("model stream content delta must be a string")
        if content:
            content_parts.append(content)
            coalescer.push(content)
        _consume_tool_calls(delta.get("tool_calls"), tool_parts)


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

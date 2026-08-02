from __future__ import annotations

import json
from collections.abc import Iterable
from typing import cast


class SseDecodeError(ValueError):
    """Raised when a test stream violates the bounded SSE/JSON contract."""


def decode_sse_json(
    chunks: Iterable[bytes],
    *,
    max_stream_bytes: int = 256 * 1024,
    max_event_bytes: int = 64 * 1024,
    max_events: int = 64,
) -> list[dict[str, object]]:
    """Decode bounded SSE ``data`` records without using the AG-UI SDK.

    The independent decoder makes the encoder round-trip meaningful. It accepts
    arbitrary byte fragmentation and standard CRLF input, but deliberately
    requires a complete blank-line-terminated stream.
    """

    if min(max_stream_bytes, max_event_bytes, max_events) <= 0:
        raise ValueError("decoder limits must be positive")

    wire = bytearray()
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise TypeError("SSE chunks must be bytes")
        if len(wire) + len(chunk) > max_stream_bytes:
            raise SseDecodeError("SSE stream exceeds max_stream_bytes")
        wire.extend(chunk)

    try:
        text = bytes(wire).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SseDecodeError("SSE stream is not valid UTF-8") from exc

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n\n"):
        raise SseDecodeError("SSE stream is not blank-line terminated")

    decoded: list[dict[str, object]] = []
    for block in normalized.split("\n\n"):
        if not block:
            continue
        data_lines: list[str] = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            field, separator, value = line.partition(":")
            if field != "data":
                continue
            data_lines.append(value[1:] if separator and value.startswith(" ") else value)

        if not data_lines:
            continue
        data = "\n".join(data_lines)
        if len(data.encode("utf-8")) > max_event_bytes:
            raise SseDecodeError("SSE event exceeds max_event_bytes")
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise SseDecodeError("SSE data is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise SseDecodeError("SSE JSON payload must be an object")
        decoded.append(cast(dict[str, object], payload))
        if len(decoded) > max_events:
            raise SseDecodeError("SSE stream exceeds max_events")

    return decoded

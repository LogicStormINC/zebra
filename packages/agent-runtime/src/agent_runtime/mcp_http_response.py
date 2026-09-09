"""Bounded response framing for the supported HTTP MCP protocol subset."""

import json
import time
from typing import BinaryIO

from agent_runtime.mcp_protocol import MAX_MCP_FRAME_BYTES, McpProtocolError


def read_response(
    stream: BinaryIO, content_type: str, request_id: object, deadline: float
) -> dict[str, object]:
    if content_type == "application/json":
        message = _message(stream.read(MAX_MCP_FRAME_BYTES + 1))
        _correlate(message, request_id)
        return message
    if content_type != "text/event-stream":
        raise McpProtocolError("MCP response has unsupported content type")
    consumed = 0
    data: list[bytes] = []
    while time.monotonic() < deadline:
        line = stream.readline(MAX_MCP_FRAME_BYTES + 1 - consumed)
        if not line:
            raise McpProtocolError("MCP event stream ended before its response")
        consumed += len(line)
        if consumed > MAX_MCP_FRAME_BYTES:
            raise McpProtocolError("MCP event stream exceeds the frame limit")
        line = line.rstrip(b"\r\n")
        if line:
            field, separator, value = line.partition(b":")
            if field == b"data":
                data.append(value.removeprefix(b" ") if separator else b"")
            continue
        payload = b"\n".join(data)
        data.clear()
        if not payload:
            continue
        message = _message(payload)
        if "method" in message:
            if "id" in message:
                raise McpProtocolError("MCP server requests are unsupported")
            if not isinstance(message["method"], str):
                raise McpProtocolError("MCP notification has invalid method")
            continue
        _correlate(message, request_id)
        return message
    raise McpProtocolError("MCP event stream exceeded its deadline")


def _message(payload: bytes) -> dict[str, object]:
    if len(payload) > MAX_MCP_FRAME_BYTES:
        raise McpProtocolError("MCP response exceeds the frame limit")
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise McpProtocolError("MCP response contains invalid JSON") from exc
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise McpProtocolError("MCP response contains an invalid message")
    return message


def _correlate(message: dict[str, object], request_id: object) -> None:
    if (
        "method" in message
        or type(message.get("id")) is not int
        or (request_id is not None and message["id"] != request_id)
        or ("result" in message) == ("error" in message)
    ):
        raise McpProtocolError("MCP response does not match the request")

"""Deterministic OpenAI-compatible model fixture for the Cloud Effect E2E."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_MODEL = "zebra-cloud-effect-e2e"
_TOOL_CALL = {
    "index": 0,
    "id": "call-cloud-effect",
    "type": "function",
    "function": {
        "name": "command__run",
        "arguments": json.dumps({"command": ["touch", "effect-marker"]}),
    },
}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/chat/completions":
            self._write_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
            return
        response = _completion(request)
        if request.get("stream") is True:
            self._write_stream(response)
            return
        self._write_json(HTTPStatus.OK, response)

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _write_stream(self, response: dict[str, object]) -> None:
        choice = response["choices"][0]
        assert isinstance(choice, dict)
        message = choice["message"]
        assert isinstance(message, dict)
        payload = {
            "id": response["id"],
            "model": response["model"],
            "choices": [
                {
                    "delta": {
                        "content": message["content"],
                        **(
                            {"tool_calls": message["tool_calls"]}
                            if "tool_calls" in message
                            else {}
                        ),
                    },
                    "finish_reason": choice["finish_reason"],
                }
            ],
        }
        encoded = f"data: {json.dumps(payload, separators=(',', ':'))}\n\ndata: [DONE]\n\n".encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _completion(request: object) -> dict[str, object]:
    payload = request if isinstance(request, dict) else {}
    messages = payload.get("messages")
    has_tool_result = isinstance(messages, list) and any(
        isinstance(message, dict) and message.get("role") == "tool" for message in messages
    )
    has_tools = bool(payload.get("tools"))
    if not has_tools:
        message = {"role": "assistant", "content": "Cloud Effect E2E"}
        reason = "stop"
    elif has_tool_result:
        message = {"role": "assistant", "content": "Cloud effect completed."}
        reason = "stop"
    else:
        message = {
            "role": "assistant",
            "content": "Running deterministic workspace effect.",
            "tool_calls": [_TOOL_CALL],
        }
        reason = "tool_calls"
    return {
        "id": "chatcmpl-cloud-effect-e2e",
        "model": _MODEL,
        "choices": [{"message": message, "finish_reason": reason}],
    }


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), _Handler).serve_forever()

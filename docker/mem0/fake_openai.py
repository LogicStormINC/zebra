"""Deterministic OpenAI-compatible embedding endpoint for the Mem0 OSS spike."""

from __future__ import annotations

import hashlib
import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

EMBEDDING_DIMENSIONS = 1536
MAX_REQUEST_BYTES = 1_048_576


def deterministic_embedding(text: str, *, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(dimensions)]
    magnitude = sum(value * value for value in values) ** 0.5
    return [value / magnitude for value in values]


class FakeOpenAIHandler(BaseHTTPRequestHandler):
    server_version = "ZebraMem0Spike/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/chat/completions":
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": {"message": "LLM calls are forbidden in infer=false spike"}},
            )
            return
        if self.path != "/v1/embeddings":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        try:
            body = self._read_json()
            texts = _embedding_inputs(body.get("input"))
        except (ValueError, json.JSONDecodeError) as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc)}})
            return

        if any("zebra-provider-failure" in text for text in texts):
            self._write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": {"message": "deterministic provider failure"}},
            )
            return

        if any("zebra-provider-timeout" in text for text in texts):
            time.sleep(2)

        dimensions = (
            8
            if any("zebra-dimension-mismatch" in text for text in texts)
            else EMBEDDING_DIMENSIONS
        )
        self._write_json(
            HTTPStatus.OK,
            {
                "object": "list",
                "data": [
                    {
                        "object": "embedding",
                        "embedding": deterministic_embedding(text, dimensions=dimensions),
                        "index": index,
                    }
                    for index, text in enumerate(texts)
                ],
                "model": "zebra-mem0-spike-embedding",
                "usage": {"prompt_tokens": 0, "total_tokens": 0},
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            raise ValueError("request body size is invalid")
        payload = json.loads(self.rfile.read(content_length))
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        return payload

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except BrokenPipeError:
            pass


def _embedding_inputs(value: object) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return value
    raise ValueError("input must be a non-empty string or string list")


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8080), FakeOpenAIHandler).serve_forever()


if __name__ == "__main__":
    main()

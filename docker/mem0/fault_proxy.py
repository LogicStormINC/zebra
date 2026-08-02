"""Tiny test-only proxy for deterministic provider response-loss faults."""

from __future__ import annotations

import http.client
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class FaultProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    _drop_lock = threading.Lock()
    _dropped = False

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._forward()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/__test__/reset-fault":
            with self._drop_lock:
                self._dropped = False
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._forward()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        self._forward()

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        self._forward()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        self._forward()

    def _forward(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            return

        target = urlsplit(self.path)
        body = self._read_body()
        connection = http.client.HTTPConnection(
            os.environ.get("UPSTREAM_HOST", "mem0-api"),
            int(os.environ.get("UPSTREAM_PORT", "8000")),
            timeout=float(os.environ.get("UPSTREAM_TIMEOUT", "30")),
        )
        try:
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"host", "content-length", "connection"}
            }
            headers["Host"] = os.environ.get("UPSTREAM_HOST", "mem0-api")
            if body:
                headers["Content-Length"] = str(len(body))
            upstream_path = target.path or "/"
            if target.query:
                upstream_path += f"?{target.query}"
            connection.request(self.command, upstream_path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            if self._should_drop_response(target.path or "/"):
                self.close_connection = True
                return
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() in {"connection", "content-length", "transfer-encoding"}:
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        finally:
            connection.close()

    def _read_body(self) -> bytes | None:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else None

    def _should_drop_response(self, path: str) -> bool:
        if self.command != os.environ.get("DROP_ONCE_METHOD", "POST"):
            return False
        if path != os.environ.get("DROP_ONCE_PATH", "/memories"):
            return False
        with self._drop_lock:
            if self._dropped:
                return False
            self._dropped = True
            return True

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8080), FaultProxyHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Remote legacy HTTP+SSE only; reuse the existing bounded MCP session contract."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import BinaryIO, cast

from agent_core.domain.extensions import McpConnection

from agent_runtime.mcp_http import McpHttpSession, _NoRedirectHandler
from agent_runtime.mcp_http_authorization import resolve_bearer_header
from agent_runtime.mcp_http_egress import PublicMcpHttpsHandler
from agent_runtime.mcp_http_response import read_response
from agent_runtime.mcp_protocol import MAX_MCP_FRAME_BYTES, McpProtocolError


@dataclass
class McpSseSession(McpHttpSession):
    _stream: BinaryIO | None = field(default=None, init=False, repr=False)
    _message_endpoint: str | None = field(default=None, init=False, repr=False)

    @property
    def requested_protocol_version(self) -> str:
        return "2024-11-05"

    @property
    def supported_protocol_versions(self) -> frozenset[str]:
        return frozenset({"2024-11-05"})

    def __enter__(self) -> McpSseSession:
        try:
            super().__enter__()
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_: object) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        self._message_endpoint = None

    def _headers(self, payload: Mapping[str, object]) -> dict[str, str]:
        endpoint = self.server.url
        McpConnection.validate_endpoint(endpoint)
        if self.server.bearer_token_env is not None:
            raise McpProtocolError("cloud SSE cannot use environment credentials")
        headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
        try:
            if self.frame_authorizer is not None:
                self.frame_authorizer(endpoint, payload)
            if self.credential_resolver is not None:
                headers["Authorization"] = resolve_bearer_header(
                    self.credential_resolver, endpoint, payload,
                )
        except Exception:
            raise McpProtocolError("MCP SSE request authorization failed") from None
        return headers

    def _send_frame(self, payload: Mapping[str, object]) -> tuple[str, str]:
        frame = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
        if len(frame) > MAX_MCP_FRAME_BYTES:
            raise McpProtocolError("MCP SSE request exceeds frame limit")
        deadline = time.monotonic() + self.timeout_seconds
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), PublicMcpHttpsHandler(), _NoRedirectHandler(),
        )
        try:
            if self._stream is None:
                request = urllib.request.Request(
                    self.server.url, headers=self._headers(payload), method="GET",
                )
                response = opener.open(request, timeout=self.timeout_seconds)
                self._stream = cast(BinaryIO, response)
                if response.headers.get_content_type() != "text/event-stream":
                    raise McpProtocolError("MCP SSE endpoint did not return an event stream")
                self._message_endpoint = _read_endpoint(self._stream, self.server.url, deadline)
            assert self._message_endpoint is not None
            # The derived target is same-origin HTTPS only; the socket handler
            # revalidates and pins public DNS for GET and every POST separately.
            request = urllib.request.Request(
                self._message_endpoint, data=frame, headers=self._headers(payload), method="POST",
            )
            with opener.open(request, timeout=self.timeout_seconds):
                pass
            if "id" not in payload:
                return "application/json", ""
            message = read_response(self._stream, "text/event-stream", payload["id"], deadline)
            return "application/json", json.dumps(message)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise McpProtocolError(f"MCP SSE returned HTTP {exc.code}") from None
        except (OSError, ValueError) as exc:
            if isinstance(exc, McpProtocolError):
                raise
            raise McpProtocolError("MCP SSE request failed") from None


def _read_endpoint(stream: BinaryIO, original: str, deadline: float) -> str:
    consumed = 0
    event = b""
    data: list[bytes] = []
    while time.monotonic() < deadline:
        line = stream.readline(MAX_MCP_FRAME_BYTES + 1 - consumed)
        if not line:
            break
        consumed += len(line)
        if consumed > MAX_MCP_FRAME_BYTES:
            raise McpProtocolError("MCP SSE endpoint event exceeds frame limit")
        line = line.rstrip(b"\r\n")
        if line:
            key, _, value = line.partition(b":")
            if key == b"event":
                event = value.removeprefix(b" ")
            elif key == b"data":
                data.append(value.removeprefix(b" "))
            continue
        if event == b"endpoint" and data:
            location = b"\n".join(data).decode("utf-8")
            if any(character.isspace() for character in location) or "\\" in location:
                raise McpProtocolError("MCP SSE endpoint contains invalid characters")
            target = urllib.parse.urljoin(original, location)
            McpConnection.validate_endpoint(target)
            a, b = urllib.parse.urlsplit(original), urllib.parse.urlsplit(target)
            if (a.scheme, a.hostname, a.port or 443) != (b.scheme, b.hostname, b.port or 443):
                raise McpProtocolError("MCP SSE endpoint changed origin")
            return target
        event, data = b"", []
    raise McpProtocolError("MCP SSE endpoint event unavailable")

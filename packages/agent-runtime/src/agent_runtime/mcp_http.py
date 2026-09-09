from __future__ import annotations

import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_tools import McpProxyRequest, McpProxyResponse
from agent_tools.web_gateway import WebGatewayError

from agent_runtime.mcp_http_authorization import McpHttpCredentialResolver, resolve_bearer_header
from agent_runtime.mcp_http_egress import PublicMcpHttpsHandler
from agent_runtime.mcp_http_response import read_response
from agent_runtime.mcp_protocol import (
    MAX_MCP_FRAME_BYTES,
    MCP_PROTOCOL_VERSION_LATEST,
    SUPPORTED_PROTOCOL_VERSIONS,
    McpHttpServerSpec,
    McpProtocolError,
)

# The discovery/tool parsing/validation helpers are transport-agnostic; reuse
# them from the stdio transport so both transports enforce identical bounds.
from agent_runtime.mcp_stdio import (
    MAX_MCP_LIST_PAGES,
    MAX_MCP_OUTPUT_BYTES,
    MAX_MCP_TOOLS_PER_SERVER,
    MAX_MCP_TOOLS_TOTAL,
    MCP_CALL_TIMEOUT_SECONDS,
    MCP_DISCOVERY_TIMEOUT_SECONDS,
    DiscoveredMcpTool,
    _normalize_tool_result,
    _parse_tool,
    _validate_tool_arguments,
)
from agent_runtime.web_gateway import reject_non_public_resolution


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        # Redirects are an SSRF vector; fail closed instead of following them.
        return None


@dataclass
class McpHttpSession:
    """Per-operation HTTP session with bounded JSON/SSE response framing."""

    server: McpHttpServerSpec
    timeout_seconds: float
    credential_resolver: McpHttpCredentialResolver | None = field(default=None, repr=False)
    frame_authorizer: Callable[[str, Mapping[str, object]], None] | None = field(
        default=None, repr=False
    )
    _request_id: int = field(default=0, init=False)
    _capabilities: dict[str, object] = field(default_factory=dict, init=False)
    _protocol_version: str | None = field(default=None, init=False)
    _session_id: str | None = field(default=None, init=False, repr=False)
    _has_server_instructions: bool = field(default=False, init=False)

    def __enter__(self) -> McpHttpSession:
        if self.timeout_seconds <= 0:
            raise ValueError("MCP timeout must be positive")
        result = self.request(
            "initialize",
            {
                "protocolVersion": self.requested_protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "zebra-agent", "version": "0.1.0"},
            },
        )
        server_version = result.get("protocolVersion")
        if (
            not isinstance(server_version, str)
            or server_version not in self.supported_protocol_versions
        ):
            raise McpProtocolError(
                f"MCP server {self.server.name} returned an unsupported protocol version"
            )
        self._protocol_version = server_version
        capabilities = result.get("capabilities")
        if not isinstance(capabilities, Mapping):
            raise McpProtocolError(f"MCP server {self.server.name} has invalid capabilities")
        self._capabilities = dict(capabilities)
        self._has_server_instructions = result.get("instructions") is not None
        self.notify("notifications/initialized")
        return self

    def __exit__(self, *_: object) -> None:
        return None

    @property
    def requested_protocol_version(self) -> str:
        return MCP_PROTOCOL_VERSION_LATEST

    @property
    def supported_protocol_versions(self) -> frozenset[str]:
        return SUPPORTED_PROTOCOL_VERSIONS

    def request(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self._request_id += 1
        payload: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = dict(params)
        message = self._post(payload)
        message_id = message.get("id")
        if type(message_id) is not int or message_id != self._request_id:
            raise McpProtocolError(f"MCP server {self.server.name} returned an unexpected message")
        error = message.get("error")
        if error is not None:
            raise McpProtocolError(f"MCP server {self.server.name} returned a protocol error")
        result = message.get("result")
        if not isinstance(result, dict):
            raise McpProtocolError(f"MCP server {self.server.name} returned an invalid result")
        return result

    def supports(self, capability: str) -> bool:
        return capability in self._capabilities

    @property
    def has_server_instructions(self) -> bool:
        return self._has_server_instructions

    @property
    def protocol_version(self) -> str | None:
        return self._protocol_version

    def notify(self, method: str) -> None:
        """Require successful delivery before continuing the handshake."""
        self._send_frame({"jsonrpc": "2.0", "method": method})

    def _post(self, payload: Mapping[str, object]) -> dict[str, object]:
        content_type, text = self._send_frame(payload)
        return _parse_response_message(self.server.name, content_type, text)

    def _send_frame(self, payload: Mapping[str, object]) -> tuple[str, str]:
        endpoint = self.server.url
        if self.frame_authorizer is not None:
            try:
                self.frame_authorizer(endpoint, payload)
            except Exception:
                raise McpProtocolError("MCP request authorization failed") from None
        if self.credential_resolver is not None and self.server.bearer_token_env is not None:
            raise McpProtocolError("MCP scoped authorization cannot use environment credentials")
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme != "https":
            raise McpProtocolError(f"MCP server {self.server.name} url must use https")
        hostname = parsed.hostname
        if not hostname:
            raise McpProtocolError(f"MCP server {self.server.name} has an invalid url")
        port = parsed.port or 443
        try:
            reject_non_public_resolution(hostname, port=port)
        except WebGatewayError as exc:
            raise McpProtocolError(
                f"MCP server {self.server.name} url resolves to a blocked address"
            ) from exc
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "Zebra-Agent-MCP-HTTP/1.0",
        }
        if self._session_id is not None:
            headers["MCP-Session-Id"] = self._session_id
        if self._protocol_version is not None:
            headers["MCP-Protocol-Version"] = self._protocol_version
        bearer_env = self.server.bearer_token_env
        if bearer_env:
            token = os.environ.get(bearer_env)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        frame = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
        if len(frame) > MAX_MCP_FRAME_BYTES:
            raise McpProtocolError(f"MCP request to {self.server.name} exceeds the frame limit")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), PublicMcpHttpsHandler(), _NoRedirectHandler()
        )
        if self.credential_resolver is not None:
            headers["Authorization"] = resolve_bearer_header(
                self.credential_resolver, endpoint, json.loads(frame)
            )
        request = urllib.request.Request(
            endpoint,
            data=frame,
            headers=headers,
            method="POST",
        )
        deadline = time.monotonic() + self.timeout_seconds
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                session_id = response.headers.get("MCP-Session-Id")
                if session_id is not None:
                    if (
                        not session_id
                        or len(session_id) > 4096
                        or any(not 0x21 <= ord(char) <= 0x7E for char in session_id)
                        or (
                            payload.get("method") != "initialize" and session_id != self._session_id
                        )
                    ):
                        raise McpProtocolError("MCP server returned an invalid session header")
                    self._session_id = session_id
                if "id" not in payload:
                    return "application/json", ""
                content_type = response.headers.get("Content-Type") or ""
                content_type = content_type.partition(";")[0].strip().lower()
                message = read_response(response, content_type, payload["id"], deadline)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise McpProtocolError(
                    f"MCP server {self.server.name} attempted an unsafe redirect"
                ) from None
            raise McpProtocolError(
                f"MCP server {self.server.name} returned HTTP error {exc.code}"
            ) from None
        except McpProtocolError:
            raise
        except (OSError, ValueError):
            raise McpProtocolError(f"MCP server {self.server.name} request failed") from None
        return "application/json", json.dumps(message, ensure_ascii=False, separators=(",", ":"))


class StreamableHttpMcpTransport:
    """Streamable HTTP transport implementing the McpProxyTransport contract."""

    def __init__(
        self,
        servers: Sequence[McpHttpServerSpec],
        allowed_tools: Sequence[str] | None = None,
        *,
        max_output_bytes: int | None = None,
    ) -> None:
        if max_output_bytes is None:
            max_output_bytes = MAX_MCP_OUTPUT_BYTES
        if max_output_bytes is not None and max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self._servers = {server.name: server for server in servers}
        if len(self._servers) != len(servers):
            raise McpProtocolError("MCP server names must be unique")
        discovered: list[DiscoveredMcpTool] = []
        for server_name in sorted(self._servers):
            discovered.extend(_discover_http_server(self._servers[server_name]))
        if len(discovered) > MAX_MCP_TOOLS_TOTAL:
            raise McpProtocolError(
                f"configured MCP servers expose more than {MAX_MCP_TOOLS_TOTAL} tools"
            )
        all_tools = {(tool.server_name, tool.remote_name): tool for tool in discovered}
        if len(all_tools) != len(discovered):
            raise McpProtocolError("configured MCP servers expose duplicate tool names")
        aliases = [tool.definition.name.replace(".", "__") for tool in discovered]
        if len(set(aliases)) != len(aliases):
            raise McpProtocolError("configured MCP tool names collide after provider normalization")
        if allowed_tools is not None:
            normalized = normalize_mcp_allowlist(allowed_tools)
            available = {tool.definition.name for tool in discovered}
            missing = sorted(set(normalized) - available)
            if missing:
                raise McpProtocolError(f"selected MCP tools are unavailable: {', '.join(missing)}")
            selected = set(normalized)
            discovered = [tool for tool in discovered if tool.definition.name in selected]
        self._tools = {(tool.server_name, tool.remote_name): tool for tool in discovered}
        self._max_output_bytes = max_output_bytes
        self.model_tools = tuple(
            tool.definition for tool in sorted(discovered, key=lambda item: item.definition.name)
        )

    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        key = (request.target.server_name, request.target.tool_name)
        if key not in self._tools:
            raise McpProtocolError("MCP tool is not in the configured discovery catalog")
        _validate_tool_arguments(request.arguments, self._tools[key].definition.parameters)
        server = self._servers[request.target.server_name]
        with McpHttpSession(server, MCP_CALL_TIMEOUT_SECONDS) as session:
            result = session.request(
                "tools/call",
                {"name": request.target.tool_name, "arguments": request.arguments},
            )
        output = _normalize_tool_result(
            request,
            result,
            max_output_bytes=self._max_output_bytes,
        )
        return McpProxyResponse(
            output=output,
            metadata={
                "mcp_is_error": result.get("isError") is True,
                "transport": "http",
                "untrusted_output": True,
            },
        )


def _discover_http_server(server: McpHttpServerSpec) -> list[DiscoveredMcpTool]:
    with McpHttpSession(server, MCP_DISCOVERY_TIMEOUT_SECONDS) as session:
        return _discover_http_tools(session)


def _discover_http_tools(
    session: McpHttpSession,
    *,
    parse_tool: Callable[[str, object], DiscoveredMcpTool] = _parse_tool,
) -> list[DiscoveredMcpTool]:
    """Share paging/parser bounds with scoped cloud catalog discovery."""
    server = session.server
    tools: list[DiscoveredMcpTool] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    seen_names: set[str] = set()
    seen_aliases: set[str] = set()
    if not session.supports("tools"):
        return []
    for _ in range(MAX_MCP_LIST_PAGES):
        params = {"cursor": cursor} if cursor is not None else None
        result = session.request("tools/list", params)
        entries = result.get("tools")
        if not isinstance(entries, list):
            raise McpProtocolError(f"MCP server {server.name} returned an invalid tool list")
        for entry in entries:
            tool = parse_tool(server.name, entry)
            if tool.remote_name in seen_names:
                raise McpProtocolError("MCP discovery returned duplicate tool names")
            if tool.definition.name in seen_aliases:
                raise McpProtocolError("MCP discovery returned colliding tool aliases")
            seen_names.add(tool.remote_name)
            seen_aliases.add(tool.definition.name)
            tools.append(tool)
            if len(tools) > MAX_MCP_TOOLS_PER_SERVER:
                raise McpProtocolError(
                    f"MCP server {server.name} exposes more than {MAX_MCP_TOOLS_PER_SERVER} tools"
                )
        next_cursor = result.get("nextCursor")
        if next_cursor is None:
            return tools
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
            raise McpProtocolError(f"MCP server {server.name} returned an invalid cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise McpProtocolError(f"MCP server {server.name} exceeded the tool-list page limit")


def _parse_response_message(server_name: str, content_type: str, text: str) -> dict[str, object]:
    return read_response(io.BytesIO(text.encode()), content_type, None, time.monotonic() + 5)

"""Pinned cloud catalogs through the existing MCP proxy and HTTP framing."""

import hashlib
import json
from collections.abc import Callable, Mapping

from agent_core.domain.extension_snapshots import ExtensionSnapshot, McpSnapshotEntry
from agent_core.domain.mcp_catalog import McpToolCatalog
from agent_tools import McpProxyRequest, McpProxyResponse, McpToolTarget

from agent_runtime.mcp_catalog_discovery import _DiscoveryServer, _parse_cloud_tool
from agent_runtime.mcp_http import McpHttpSession
from agent_runtime.mcp_http_authorization import McpHttpBearerCredential
from agent_runtime.mcp_protocol import McpProtocolError
from agent_runtime.mcp_sse import McpSseSession
from agent_runtime.mcp_stdio import (
    MAX_MCP_OUTPUT_BYTES,
    MAX_MCP_TOOLS_TOTAL,
    MCP_CALL_TIMEOUT_SECONDS,
    DiscoveredMcpTool,
    _normalize_tool_result,
    _validate_tool_arguments,
)

type FrameAuthority = Callable[
    [McpSnapshotEntry, McpProxyRequest, str, Mapping[str, object]],
    McpHttpBearerCredential | None,
]


class CloudMcpTransport:
    """Trusted composition supplies a recovered snapshot and live per-frame guard.

    This transport is not an authorization source. The guard must verify live
    scope, revocation, operation policy and Worker fence before each HTTP frame.
    """

    def __init__(
        self,
        snapshot: ExtensionSnapshot,
        catalogs: tuple[McpToolCatalog, ...],
        *,
        authorize: FrameAuthority,
        max_output_bytes: int = MAX_MCP_OUTPUT_BYTES,
    ) -> None:
        snapshot = ExtensionSnapshot.model_validate(snapshot.model_dump())
        if max_output_bytes <= 0 or not callable(authorize):
            raise ValueError("cloud MCP requires bounded output and live authorization")
        by_id = {catalog.connection.connection_id: catalog for catalog in catalogs}
        if len(by_id) != len(catalogs) or set(by_id) != {
            entry.connection.connection_id for entry in snapshot.mcp
        }:
            raise ValueError("cloud MCP catalogs must match the exact snapshot")
        self._routes: dict[str, tuple[McpSnapshotEntry, str, DiscoveredMcpTool]] = {}
        definitions = []
        for entry in snapshot.mcp:
            catalog = McpToolCatalog.model_validate(
                by_id[entry.connection.connection_id].model_dump()
            )
            if catalog.connection != entry.connection or catalog.digest != entry.catalog_digest:
                raise ValueError("cloud MCP catalog binding mismatch")
            if entry.connection.auth_mode.value not in ("none", "bearer"):
                raise ValueError("cloud MCP authentication is unsupported")
            tools = {tool.name: tool for tool in catalog.tools}
            if not set(entry.permissions.tools) <= tools.keys():
                raise ValueError("cloud MCP selection names an unavailable tool")
            # Provider normalization adds two underscores per separator: total alias <= 64.
            server = "s" + hashlib.sha256(entry.connection.connection_id.encode()).hexdigest()[:24]
            for name in entry.permissions.tools:
                tool = tools[name]
                parsed = _parse_cloud_tool(
                    server,
                    {
                        "name": name,
                        "description": tool.description,
                        "inputSchema": json.loads(tool.input_schema_json),
                    },
                )
                alias = parsed.definition.name
                if alias in self._routes:
                    raise ValueError("cloud MCP tool aliases collide")
                self._routes[alias] = (entry, catalog.protocol_version, parsed)
                definitions.append(parsed.definition)
        if len(definitions) > MAX_MCP_TOOLS_TOTAL:
            raise ValueError("cloud MCP tool selection exceeds model tool limit")
        self.model_tools = tuple(sorted(definitions, key=lambda tool: tool.name))
        self._authorize = authorize
        self._max_output_bytes = max_output_bytes

    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        route = self._routes.get(f"mcp.{request.target.server_name}.{request.target.tool_name}")
        if route is None:
            raise McpProtocolError("MCP tool is outside the selected catalog")
        entry, protocol, tool = route
        _validate_tool_arguments(request.arguments, tool.definition.parameters)
        remote = McpProxyRequest(
            request.tool_call_id,
            McpToolTarget(entry.connection.connection_id, tool.remote_name),
            request.arguments,
        )
        params_json = json.dumps(
            {"name": tool.remote_name, "arguments": remote.arguments},
            sort_keys=True,
            allow_nan=False,
        )

        def guard(endpoint: str, frame: Mapping[str, object]) -> McpHttpBearerCredential | None:
            if endpoint != entry.connection.endpoint or (
                frame.get("method") not in ("initialize", "notifications/initialized")
                and (
                    frame.get("method") != "tools/call"
                    or json.dumps(frame.get("params"), sort_keys=True, allow_nan=False)
                    != params_json
                )
            ):
                raise McpProtocolError("MCP frame differs from selected operation")
            return self._authorize(entry, remote, endpoint, frame)

        def anonymous(endpoint: str, frame: Mapping[str, object]) -> None:
            if guard(endpoint, frame) is not None:
                raise McpProtocolError("anonymous MCP cannot receive credentials")

        def bearer(endpoint: str, frame: Mapping[str, object]) -> McpHttpBearerCredential:
            result = guard(endpoint, frame)
            if not isinstance(result, McpHttpBearerCredential):
                raise McpProtocolError("MCP credentials unavailable")
            return result

        authenticated = entry.connection.auth_mode.value == "bearer"
        session_type = McpSseSession if entry.connection.transport == "sse" else McpHttpSession
        with session_type(
            _DiscoveryServer(entry.connection.endpoint),
            MCP_CALL_TIMEOUT_SECONDS,
            credential_resolver=bearer if authenticated else None,
            frame_authorizer=None if authenticated else anonymous,
        ) as session:
            if session.protocol_version != protocol:
                raise McpProtocolError("MCP protocol changed; refresh its catalog")
            result = session.request("tools/call", json.loads(params_json))
        return McpProxyResponse(
            output=_normalize_tool_result(remote, result, max_output_bytes=self._max_output_bytes),
            metadata={
                "transport": "sse" if entry.connection.transport == "sse" else "http",
                "mcp_is_error": result.get("isError") is True,
            },
        )

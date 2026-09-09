"""HTTP metadata discovery for a trusted caller; never an execution authorization."""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agent_core.domain.extensions import McpConnection, OpaqueExtensionId
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from pydantic import TypeAdapter, ValidationError

from agent_runtime.mcp_http import (
    McpHttpSession,
    _discover_http_tools,
)
from agent_runtime.mcp_http_authorization import McpHttpCredentialResolver
from agent_runtime.mcp_protocol import McpProtocolError
from agent_runtime.mcp_sse import McpSseSession
from agent_runtime.mcp_stdio import MCP_DISCOVERY_TIMEOUT_SECONDS, DiscoveredMcpTool, _parse_tool


def _parse_cloud_tool(server_name: str, value: object) -> DiscoveredMcpTool:
    """Keep remote identifiers verbatim; local name rules apply only to aliases."""
    if not isinstance(value, dict):
        raise McpProtocolError("MCP discovery returned an invalid tool")
    try:
        name = TypeAdapter(OpaqueExtensionId).validate_python(value.get("name"))
    except ValidationError:
        raise McpProtocolError("MCP discovery returned an invalid tool name") from None
    alias = "t" + hashlib.sha256(name.encode()).hexdigest()[:30]
    return _parse_tool(server_name, value, remote_alias=alias)


@dataclass(frozen=True)
class _DiscoveryServer:
    url: str
    name: str = "discovery"
    bearer_token_env: None = None


def discover_mcp_tool_catalog(
    connection: McpConnection,
    *,
    credential_resolver: McpHttpCredentialResolver | None = None,
    frame_authorizer: Callable[[str, Mapping[str, object]], None] | None = None,
) -> McpToolCatalog:
    """Caller authorizes refresh before entry; authenticated frames reauthorize.

    No storage write happens here. Publish only the complete returned catalog
    using the revision-checked store. Disabled connections may be management-tested.
    """
    connection = McpConnection.model_validate(connection.model_dump())
    if connection.auth_mode.value == "none":
        if credential_resolver is not None:
            raise McpProtocolError("unauthenticated discovery cannot receive credentials")
    elif (
        connection.auth_mode.value != "bearer"
        or connection.auth_state.value != "ready"
        or credential_resolver is None
    ):
        raise McpProtocolError("MCP discovery authentication is unavailable")
    session_type = McpSseSession if connection.transport == "sse" else McpHttpSession
    with session_type(
        _DiscoveryServer(connection.endpoint),
        MCP_DISCOVERY_TIMEOUT_SECONDS,
        credential_resolver=credential_resolver,
        frame_authorizer=frame_authorizer,
    ) as session:
        tools = _discover_http_tools(session, parse_tool=_parse_cloud_tool)
        assert session.protocol_version is not None
        return McpToolCatalog(
            connection=connection,
            protocol_version=session.protocol_version,
            tools=tuple(
                McpCatalogTool(
                    name=tool.remote_name,
                    description=tool.definition.description,
                    input_schema_json=json.dumps(tool.definition.parameters, allow_nan=False),
                )
                for tool in tools
            ),
        )

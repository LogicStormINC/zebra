from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256

from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.modeling import ModelToolDefinition
from agent_tools import McpProxyRequest, McpProxyResponse
from agent_tools.mcp_proxy import JsonValue

from agent_runtime.mcp_protocol import McpProtocolError, McpServerSpec, StdioMcpSession

MAX_MCP_TOOLS_PER_SERVER = 16
MAX_MCP_TOOLS_TOTAL = 32
MAX_MCP_LIST_PAGES = 4
MAX_MCP_SCHEMA_BYTES = 16 * 1024
MAX_MCP_OUTPUT_BYTES = 32 * 1024
MCP_DISCOVERY_TIMEOUT_SECONDS = 5.0
MCP_CALL_TIMEOUT_SECONDS = 30.0
_TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class DiscoveredMcpTool:
    server_name: str
    remote_name: str
    definition: ModelToolDefinition
    operation_key_arguments: tuple[str, ...] = ()
    operation_key_path_arguments: frozenset[str] = frozenset()


class LocalStdioMcpTransport:
    def __init__(
        self,
        servers: Sequence[McpServerSpec],
        allowed_tools: Sequence[str] | None = None,
        *,
        max_output_bytes: int | None = MAX_MCP_OUTPUT_BYTES,
    ) -> None:
        if max_output_bytes is not None and max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self._servers = {server.name: server for server in servers}
        if len(self._servers) != len(servers):
            raise McpProtocolError("MCP server names must be unique")
        discovered: list[DiscoveredMcpTool] = []
        for server_name in sorted(self._servers):
            discovered.extend(_discover_server(self._servers[server_name]))
        if len(discovered) > MAX_MCP_TOOLS_TOTAL:
            raise McpProtocolError(
                f"configured MCP servers expose more than {MAX_MCP_TOOLS_TOTAL} tools"
            )
        all_tools = {
            (tool.server_name, tool.remote_name): tool
            for tool in discovered
        }
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
                raise McpProtocolError(
                    f"selected MCP tools are unavailable: {', '.join(missing)}"
                )
            selected = set(normalized)
            discovered = [tool for tool in discovered if tool.definition.name in selected]
        self._tools = {
            (tool.server_name, tool.remote_name): tool
            for tool in discovered
        }
        self._max_output_bytes = max_output_bytes
        self.model_tools = tuple(
            tool.definition
            for tool in sorted(discovered, key=lambda item: item.definition.name)
        )

    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        key = (request.target.server_name, request.target.tool_name)
        if key not in self._tools:
            raise McpProtocolError("MCP tool is not in the configured discovery catalog")
        _validate_tool_arguments(request.arguments, self._tools[key].definition.parameters)
        server = self._servers[request.target.server_name]
        with StdioMcpSession(server, MCP_CALL_TIMEOUT_SECONDS) as session:
            result = session.request(
                "tools/call",
                {"name": request.target.tool_name, "arguments": request.arguments},
            )
        output = _normalize_tool_result(
            request,
            result,
            max_output_bytes=self._max_output_bytes,
        )
        metadata: dict[str, JsonValue] = {
            "mcp_is_error": result.get("isError") is True,
            "transport": "stdio",
            "untrusted_output": True,
        }
        if operation_key := self.operation_key_for(request):
            metadata["operation_key"] = operation_key
        return McpProxyResponse(output=output, metadata=metadata)

    def operation_key_for(self, request: McpProxyRequest) -> str | None:
        tool = self._tools.get((request.target.server_name, request.target.tool_name))
        return None if tool is None else _operation_key_for(tool, request.arguments)


def _discover_server(server: McpServerSpec) -> list[DiscoveredMcpTool]:
    tools: list[DiscoveredMcpTool] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    with StdioMcpSession(server, MCP_DISCOVERY_TIMEOUT_SECONDS) as session:
        if not session.supports("tools"):
            return []
        for _ in range(MAX_MCP_LIST_PAGES):
            params = {"cursor": cursor} if cursor is not None else None
            result = session.request("tools/list", params)
            entries = result.get("tools")
            if not isinstance(entries, list):
                raise McpProtocolError(f"MCP server {server.name} returned an invalid tool list")
            for entry in entries:
                tools.append(_parse_tool(server.name, entry))
                if len(tools) > MAX_MCP_TOOLS_PER_SERVER:
                    raise McpProtocolError(
                        f"MCP server {server.name} exposes more than "
                        f"{MAX_MCP_TOOLS_PER_SERVER} tools"
                    )
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tools
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise McpProtocolError(f"MCP server {server.name} returned an invalid cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
    raise McpProtocolError(f"MCP server {server.name} exceeded the tool-list page limit")


def _parse_tool(server_name: str, value: object) -> DiscoveredMcpTool:
    if not isinstance(value, dict):
        raise McpProtocolError(f"MCP server {server_name} returned an invalid tool")
    remote_name = value.get("name")
    if not isinstance(remote_name, str) or not _TOOL_NAME_RE.fullmatch(remote_name):
        raise McpProtocolError(f"MCP server {server_name} returned an unsupported tool name")
    schema = value.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise McpProtocolError(f"MCP tool {server_name}.{remote_name} requires an object schema")
    properties = schema.get("properties")
    if properties is None:
        schema = {**schema, "properties": {}}
        properties = schema["properties"]
    if not isinstance(properties, dict):
        raise McpProtocolError(f"MCP tool {server_name}.{remote_name} has invalid properties")
    required = schema.get("required", [])
    if (
        not isinstance(required, list)
        or any(not isinstance(item, str) or item not in properties for item in required)
        or len(set(required)) != len(required)
    ):
        raise McpProtocolError(f"MCP tool {server_name}.{remote_name} has invalid required fields")
    _validate_json_value(schema, f"MCP tool {server_name}.{remote_name} schema")
    if len(json.dumps(schema, separators=(",", ":")).encode()) > MAX_MCP_SCHEMA_BYTES:
        raise McpProtocolError(f"MCP tool {server_name}.{remote_name} schema is too large")
    description = value.get("description")
    if not isinstance(description, str) or not description.strip():
        description = f"Call configured MCP tool {server_name}.{remote_name}."
    description = description.strip()[:512]
    operation_key_arguments, operation_key_path_arguments = _operation_key_fields(
        server_name,
        remote_name,
        value.get("_meta"),
        properties,
    )
    return DiscoveredMcpTool(
        server_name=server_name,
        remote_name=remote_name,
        definition=ModelToolDefinition(
            name=f"mcp.{server_name}.{remote_name}",
            description=f"Untrusted external MCP capability. {description}",
            parameters=schema,
        ),
        operation_key_arguments=operation_key_arguments,
        operation_key_path_arguments=operation_key_path_arguments,
    )


def _operation_key_fields(
    server_name: str,
    tool_name: str,
    metadata: object,
    properties: Mapping[str, object],
) -> tuple[tuple[str, ...], frozenset[str]]:
    if not isinstance(metadata, Mapping):
        return (), frozenset()
    declaration = metadata.get("zebra_operation_key")
    if declaration is None:
        return (), frozenset()
    if not isinstance(declaration, Mapping):
        raise McpProtocolError(
            f"MCP tool {server_name}.{tool_name} has an invalid operation key declaration"
        )
    if set(declaration) - {"arguments", "path_arguments"}:
        raise McpProtocolError(
            f"MCP tool {server_name}.{tool_name} has an invalid operation key declaration"
        )
    arguments = declaration.get("arguments")
    path_arguments = declaration.get("path_arguments", [])
    if (
        not isinstance(arguments, list)
        or not arguments
        or any(not isinstance(name, str) or name not in properties for name in arguments)
        or len(set(arguments)) != len(arguments)
        or not isinstance(path_arguments, list)
        or any(
            not isinstance(name, str) or name not in arguments for name in path_arguments
        )
        or len(set(path_arguments)) != len(path_arguments)
    ):
        raise McpProtocolError(
            f"MCP tool {server_name}.{tool_name} has an invalid operation key declaration"
        )
    return tuple(arguments), frozenset(path_arguments)


def _operation_key_for(
    tool: DiscoveredMcpTool,
    arguments: Mapping[str, object],
) -> str | None:
    if not tool.operation_key_arguments:
        return None
    selected: dict[str, object] = {}
    for name in tool.operation_key_arguments:
        value = arguments.get(name)
        if value is None:
            return None
        if name in tool.operation_key_path_arguments:
            if not isinstance(value, str) or not value.strip():
                return None
            value = posixpath.normpath(value.strip().replace("\\", "/"))
        selected[name] = value
    encoded = json.dumps(
        {
            "arguments": selected,
            "server": tool.server_name,
            "tool": tool.remote_name,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"mcp-operation:{sha256(encoded).hexdigest()}"


def _normalize_tool_result(
    request: McpProxyRequest,
    result: Mapping[str, object],
    *,
    max_output_bytes: int | None = MAX_MCP_OUTPUT_BYTES,
) -> str:
    parts: list[str] = []
    structured = result.get("structuredContent")
    if structured is not None:
        _validate_json_value(structured, "MCP structured result")
        parts.append(json.dumps(structured, separators=(",", ":"), sort_keys=True))
    content = result.get("content", [])
    if not isinstance(content, list):
        raise McpProtocolError("MCP tool returned invalid content")
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            raise McpProtocolError("MCP tool returned an unsupported content block")
        text = block.get("text")
        if not isinstance(text, str):
            raise McpProtocolError("MCP tool returned invalid text content")
        parts.append(text)
    body = "\n".join(parts)
    if max_output_bytes is not None and len(body.encode()) > max_output_bytes:
        raise McpProtocolError("MCP tool output exceeds the configured limit")
    label = f"UNTRUSTED MCP OUTPUT ({request.target.server_name}.{request.target.tool_name})"
    return f"{label}\n{body}" if body else label


def _validate_tool_arguments(
    arguments: Mapping[str, object],
    schema: Mapping[str, object],
) -> None:
    required = schema.get("required", [])
    assert isinstance(required, list)
    missing = [name for name in required if name not in arguments]
    if missing:
        raise McpProtocolError(f"MCP tool arguments are missing: {', '.join(missing)}")
    properties = schema.get("properties", {})
    assert isinstance(properties, Mapping)
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise McpProtocolError(f"MCP tool arguments are unknown: {', '.join(unknown)}")


def _validate_json_value(value: object, label: str, *, depth: int = 0) -> None:
    if depth > 20:
        raise McpProtocolError(f"{label} exceeds the nesting limit")
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise McpProtocolError(f"{label} contains a non-finite number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, label, depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise McpProtocolError(f"{label} contains a non-string key")
            _validate_json_value(item, label, depth=depth + 1)
        return
    raise McpProtocolError(f"{label} is not JSON serializable")

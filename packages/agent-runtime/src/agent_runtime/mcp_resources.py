from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlsplit

from agent_core.domain.attachments import TextAttachmentInput

from agent_runtime.mcp_protocol import (
    McpAnyServerSpec,
    McpHttpServerSpec,
    McpProtocolError,
    McpServerSpec,
    StdioMcpSession,
)
from agent_runtime.mcp_stdio import MCP_DISCOVERY_TIMEOUT_SECONDS

MAX_MCP_RESOURCES_TOTAL = 64
MAX_MCP_RESOURCE_PAGES = 4
MAX_MCP_RESOURCE_IDS = 4
MAX_MCP_RESOURCE_URI_CHARS = 2048
MAX_MCP_RESOURCE_BYTES = 64 * 1024
MAX_MCP_RESOURCE_TOTAL_BYTES = 128 * 1024
MCP_RESOURCE_READ_TIMEOUT_SECONDS = 30.0
_TEXT_APPLICATION_TYPES = frozenset(
    {"application/json", "application/xml", "application/yaml", "application/x-yaml"}
)


@dataclass(frozen=True)
class McpResource:
    resource_id: str
    server_name: str
    uri: str
    name: str
    description: str
    mime_type: str | None
    size_bytes: int | None

    def to_safe_mapping(self) -> dict[str, object]:
        return {
            "resource_id": self.resource_id,
            "name": self.name,
            "description": self.description,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
        }


def discover_mcp_resources(servers: Sequence[McpAnyServerSpec]) -> tuple[McpResource, ...]:
    # Resources are a stdio-only capability in Phase A; HTTP servers are skipped.
    stdio_servers = [server for server in servers if not isinstance(server, McpHttpServerSpec)]
    resources: list[McpResource] = []
    for server in sorted(stdio_servers, key=lambda item: item.name):
        resources.extend(_discover_server_resources(server))
        if len(resources) > MAX_MCP_RESOURCES_TOTAL:
            raise McpProtocolError(
                f"configured MCP servers expose more than {MAX_MCP_RESOURCES_TOTAL} resources"
            )
    ids = [resource.resource_id for resource in resources]
    if len(set(ids)) != len(ids):
        raise McpProtocolError("configured MCP resource identifiers collide")
    return tuple(
        sorted(resources, key=lambda item: (item.server_name, item.name, item.resource_id))
    )


def normalize_mcp_resource_ids(value: Sequence[str]) -> tuple[str, ...]:
    if len(value) > MAX_MCP_RESOURCE_IDS:
        raise ValueError(f"mcp_resource_ids accepts at most {MAX_MCP_RESOURCE_IDS} resources")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("mcp_resource_ids must contain non-blank strings")
        normalized.append(item.strip())
    if len(set(normalized)) != len(normalized):
        raise ValueError("mcp_resource_ids must not contain duplicates")
    return tuple(sorted(normalized))


def read_mcp_resource_attachments(
    servers: Sequence[McpAnyServerSpec],
    resource_ids: Sequence[str],
) -> tuple[TextAttachmentInput, ...]:
    selected_ids = normalize_mcp_resource_ids(resource_ids)
    if not selected_ids:
        return ()
    resources = {resource.resource_id: resource for resource in discover_mcp_resources(servers)}
    missing = sorted(set(selected_ids) - set(resources))
    if missing:
        raise McpProtocolError(f"selected MCP resources are unavailable: {', '.join(missing)}")
    servers_by_name = {
        server.name: server for server in servers if not isinstance(server, McpHttpServerSpec)
    }
    attachments: list[TextAttachmentInput] = []
    total_bytes = 0
    for resource_id in selected_ids:
        resource = resources[resource_id]
        payload, media_type = _read_resource(servers_by_name[resource.server_name], resource)
        total_bytes += len(payload)
        if total_bytes > MAX_MCP_RESOURCE_TOTAL_BYTES:
            raise McpProtocolError(
                f"selected MCP resources exceed {MAX_MCP_RESOURCE_TOTAL_BYTES} bytes"
            )
        attachments.append(
            TextAttachmentInput(
                file_name=resource.name,
                media_type=media_type,
                payload=payload,
                source_type="mcp_resource",
                source_server=resource.server_name,
                source_id=resource.resource_id,
            )
        )
    return tuple(attachments)


def _discover_server_resources(server: McpServerSpec) -> list[McpResource]:
    resources: list[McpResource] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    with StdioMcpSession(server, MCP_DISCOVERY_TIMEOUT_SECONDS) as session:
        if not session.supports("resources"):
            return []
        for _ in range(MAX_MCP_RESOURCE_PAGES):
            params = {"cursor": cursor} if cursor is not None else None
            result = session.request("resources/list", params)
            entries = result.get("resources")
            if not isinstance(entries, list):
                raise McpProtocolError(
                    f"MCP server {server.name} returned an invalid resource list"
                )
            for entry in entries:
                resources.append(_parse_resource(server.name, entry))
                if len(resources) > MAX_MCP_RESOURCES_TOTAL:
                    raise McpProtocolError(
                        f"MCP server {server.name} exposes more than "
                        f"{MAX_MCP_RESOURCES_TOTAL} resources"
                    )
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return resources
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise McpProtocolError(f"MCP server {server.name} returned an invalid cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
    raise McpProtocolError(f"MCP server {server.name} exceeded the resource-list page limit")


def _parse_resource(server_name: str, value: object) -> McpResource:
    if not isinstance(value, Mapping):
        raise McpProtocolError(f"MCP server {server_name} returned an invalid resource")
    uri = _bounded_required(value.get("uri"), "resource uri", MAX_MCP_RESOURCE_URI_CHARS)
    if not urlsplit(uri).scheme or any(character.isspace() for character in uri):
        raise McpProtocolError(f"MCP server {server_name} returned an invalid resource URI")
    name = _bounded_required(value.get("name"), "resource name", 128)
    description = _bounded_optional(value.get("description"), "resource description", 512)
    mime_type = _bounded_optional(value.get("mimeType"), "resource mime type", 128) or None
    size = value.get("size")
    if size is not None and (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or size > MAX_MCP_RESOURCE_BYTES
    ):
        raise McpProtocolError(f"MCP server {server_name} returned an invalid resource size")
    resource_id = f"mcp-resource:{server_name}:{sha256(uri.encode()).hexdigest()[:32]}"
    return McpResource(
        resource_id=resource_id,
        server_name=server_name,
        uri=uri,
        name=name,
        description=description,
        mime_type=mime_type,
        size_bytes=size,
    )


def _read_resource(server: McpServerSpec, resource: McpResource) -> tuple[bytes, str]:
    with StdioMcpSession(server, MCP_RESOURCE_READ_TIMEOUT_SECONDS) as session:
        if not session.supports("resources"):
            raise McpProtocolError(f"MCP server {server.name} no longer declares resources")
        result = session.request("resources/read", {"uri": resource.uri})
    contents = result.get("contents")
    if not isinstance(contents, list) or not contents:
        raise McpProtocolError(f"MCP resource {resource.resource_id} returned no content")
    parts: list[str] = []
    resolved_type = resource.mime_type or "text/plain"
    for block in contents:
        if not isinstance(block, Mapping) or "blob" in block:
            raise McpProtocolError("MCP resource returned unsupported binary content")
        if block.get("uri") != resource.uri:
            raise McpProtocolError("MCP resource returned content for a different URI")
        text = block.get("text")
        if not isinstance(text, str):
            raise McpProtocolError("MCP resource returned invalid text content")
        block_type = block.get("mimeType", resolved_type)
        if not isinstance(block_type, str) or not _is_text_media_type(block_type):
            raise McpProtocolError("MCP resource returned an unsupported media type")
        if parts and block_type != resolved_type:
            raise McpProtocolError("MCP resource returned mixed media types")
        resolved_type = block_type
        parts.append(text)
    payload = "\n".join(parts).encode("utf-8")
    if not payload.strip():
        raise McpProtocolError("MCP resource returned blank text content")
    if len(payload) > MAX_MCP_RESOURCE_BYTES:
        raise McpProtocolError(f"MCP resource exceeds {MAX_MCP_RESOURCE_BYTES} bytes")
    return payload, resolved_type


def _is_text_media_type(value: str) -> bool:
    normalized = value.split(";", maxsplit=1)[0].strip().lower()
    return normalized.startswith("text/") or normalized in _TEXT_APPLICATION_TYPES


def _bounded_required(value: object, label: str, maximum: int) -> str:
    normalized = _bounded_optional(value, label, maximum)
    if not normalized:
        raise McpProtocolError(f"{label} must not be blank")
    return normalized


def _bounded_optional(value: object, label: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise McpProtocolError(f"{label} must be a string")
    normalized = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise McpProtocolError(f"{label} contains control characters")
    if len(normalized) > maximum:
        raise McpProtocolError(f"{label} exceeds {maximum} characters")
    return normalized

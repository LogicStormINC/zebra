from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from agent_runtime import (
    McpProtocolError,
    build_mcp_capability_inventory,
    discover_mcp_resources,
    read_mcp_resource_attachments,
)


@dataclass(frozen=True)
class _Server:
    name: str
    command: str
    args: tuple[str, ...]


def test_resource_inventory_is_safe_and_does_not_read(tmp_path: Path) -> None:
    marker = tmp_path / "read"
    inventory = build_mcp_capability_inventory((_server("resource", marker),)).to_mapping()

    assert inventory["resource_count"] == 1
    resource = inventory["servers"][0]["resources"][0]
    assert resource == {
        "resource_id": resource["resource_id"],
        "name": "brief.txt",
        "description": "A bounded fixture brief.",
        "mime_type": "text/plain",
        "size_bytes": 28,
    }
    assert str(resource["resource_id"]).startswith("mcp-resource:fixture:")
    assert "resource://fixture/brief" not in repr(inventory)
    assert not marker.exists()


def test_selected_resource_becomes_bounded_source_attachment(tmp_path: Path) -> None:
    marker = tmp_path / "read"
    server = _server("resource", marker)
    resource_id = discover_mcp_resources((server,))[0].resource_id

    attachments = read_mcp_resource_attachments((server,), (resource_id,))

    assert attachments[0].payload == b"MCP_RESOURCE_CONTEXT_136"
    assert attachments[0].source_type == "mcp_resource"
    assert attachments[0].source_server == "fixture"
    assert attachments[0].source_id == resource_id
    assert marker.read_text(encoding="utf-8") == "resource-read"


def test_resources_only_server_is_supported() -> None:
    inventory = build_mcp_capability_inventory((_server("resources-only"),)).to_mapping()

    assert inventory["tool_count"] == 0
    assert inventory["resource_count"] == 1


@pytest.mark.parametrize(
    "mode, message",
    [
        ("resource-malformed", "resource uri must not be blank"),
        ("resource-blob", "binary content"),
        ("resource-substitute", "different URI"),
        ("resource-oversized", "oversized frame"),
    ],
)
def test_resources_fail_closed(mode: str, message: str) -> None:
    server = _server(mode)
    if mode == "resource-malformed":
        with pytest.raises(McpProtocolError, match=message):
            discover_mcp_resources((server,))
        return
    resource_id = discover_mcp_resources((server,))[0].resource_id
    with pytest.raises(McpProtocolError, match=message):
        read_mcp_resource_attachments((server,), (resource_id,))


def test_removed_or_duplicate_resource_selection_fails_closed() -> None:
    server = _server("resource")
    resource_id = discover_mcp_resources((server,))[0].resource_id
    with pytest.raises(ValueError, match="duplicates"):
        read_mcp_resource_attachments((server,), (resource_id, resource_id))
    with pytest.raises(McpProtocolError, match="unavailable"):
        read_mcp_resource_attachments((server,), ("mcp-resource:fixture:missing",))


def test_resource_metadata_rejects_invalid_uri_and_control_characters() -> None:
    with pytest.raises(McpProtocolError, match="invalid resource URI"):
        discover_mcp_resources((_server("resource-invalid-uri"),))
    with pytest.raises(McpProtocolError, match="control characters"):
        discover_mcp_resources((_server("resource-invalid-name"),))
    with pytest.raises(McpProtocolError, match="invalid resource size"):
        discover_mcp_resources((_server("resource-oversized-metadata"),))


def _server(mode: str, marker: Path | None = None) -> _Server:
    script = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    args = [str(script), mode]
    if marker is not None:
        args.append(str(marker))
    return _Server(name="fixture", command=sys.executable, args=tuple(args))

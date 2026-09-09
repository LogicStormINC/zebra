"""Cloud identifiers must survive discovery without relaxing local configuration."""

from unittest.mock import Mock

import pytest
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_runtime.mcp_catalog_discovery import _parse_cloud_tool, discover_mcp_tool_catalog
from agent_runtime.mcp_protocol import McpProtocolError
from agent_runtime.mcp_stdio import _parse_tool

from tests.agent_runtime import test_mcp_catalog_discovery as fixtures

network = fixtures.network


@pytest.mark.parametrize("name", ["events.search", "tools/search", "搜索内容", "x" * 512])
def test_cloud_preserves_remote_names_and_local_rules(name, network):
    network[1][:] = [{"tools": [fixtures.tool(name)]}]
    catalog = discover_mcp_tool_catalog(fixtures.CONNECTION)
    assert catalog.tools[0].name == name
    parsed = _parse_cloud_tool("discovery", fixtures.tool(name))
    assert parsed.remote_name == name
    assert normalize_mcp_allowlist([parsed.definition.name]) == (parsed.definition.name,)
    assert parsed == _parse_cloud_tool("discovery", fixtures.tool(name))
    with pytest.raises(McpProtocolError, match="unsupported tool name"):
        _parse_tool("discovery", fixtures.tool(name))


@pytest.mark.parametrize("name", ["", " x", "x ", "x\n", "x\x00", "x" * 513, None, 7])
def test_cloud_invalid_identifiers_are_rejected(name, network):
    network[1][:] = [{"tools": [fixtures.tool(name)]}]
    with pytest.raises(McpProtocolError, match="invalid tool name"):
        discover_mcp_tool_catalog(fixtures.CONNECTION)


def test_alias_collision_is_rejected_without_losing_remote_name(monkeypatch, network):
    monkeypatch.setattr(
        "agent_runtime.mcp_catalog_discovery.hashlib.sha256",
        lambda _: Mock(hexdigest=lambda: "0" * 64),
    )
    network[1][:] = [{"tools": [fixtures.tool("a.b"), fixtures.tool("a/b")]}]
    with pytest.raises(McpProtocolError, match="colliding tool aliases"):
        discover_mcp_tool_catalog(fixtures.CONNECTION)


def test_separators_are_not_normalized_to_the_same_tool():
    tools = [_parse_cloud_tool("discovery", fixtures.tool(name)) for name in ("a.b", "a/b", "a_b")]
    assert len({tool.definition.name for tool in tools}) == 3
    assert [tool.remote_name for tool in tools] == ["a.b", "a/b", "a_b"]

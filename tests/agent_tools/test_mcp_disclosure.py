from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_tools.mcp_disclosure import (
    MCP_TOOL_CALL_NAME,
    MCP_TOOL_DESCRIBE_NAME,
    MCP_TOOL_SEARCH_NAME,
    AuthorizedMcpToolCatalog,
    McpToolDescribeTool,
    McpToolSearchTool,
)


def test_small_authorized_catalog_stays_direct() -> None:
    catalog = AuthorizedMcpToolCatalog((_definition("mcp.fixture.echo"),))

    assert not catalog.activated
    assert [tool.name for tool in catalog.model_tools] == ["mcp.fixture.echo"]
    assert catalog.resolve(_call("mcp.fixture.echo", {"value": "ok"})).name == (
        "mcp.fixture.echo"
    )


def test_oversized_catalog_exposes_only_call_bridge() -> None:
    catalog = _active_catalog()

    assert catalog.activated
    assert [tool.name for tool in catalog.model_tools] == [MCP_TOOL_CALL_NAME]
    with pytest.raises(ValueError, match="deferred MCP tools"):
        catalog.resolve(_call("mcp.fixture.echo", {"value": "blocked"}))


def test_search_and_describe_are_bounded_exact_and_untrusted() -> None:
    catalog = _active_catalog()
    matches = catalog.search("fixture echo", limit=2)

    assert [match.definition.name for match in matches] == [
        "mcp.fixture.echo",
        "mcp.fixture.echo1",
    ]
    search_result = McpToolSearchTool(catalog).handle(
        _call(MCP_TOOL_SEARCH_NAME, {"query": "fixture echo", "limit": 2})
    )
    describe_result = McpToolDescribeTool(catalog).handle(
        _call(MCP_TOOL_DESCRIBE_NAME, {"name": "mcp.fixture.echo"})
    )

    assert search_result.status is ToolCallStatus.EXECUTED
    assert search_result.output.startswith("[UNTRUSTED MCP CAPABILITY METADATA]\n")
    assert search_result.metadata["result_count"] == 2
    assert describe_result.status is ToolCallStatus.EXECUTED
    assert '"name":"mcp.fixture.echo"' in describe_result.output
    with pytest.raises(ValueError, match="cannot describe themselves"):
        catalog.describe(MCP_TOOL_SEARCH_NAME)
    with pytest.raises(ValueError, match="not authorized"):
        catalog.describe("mcp.fixture.missing")


def test_call_bridge_resolves_to_underlying_mcp_call_and_preserves_provider_view() -> None:
    catalog = _active_catalog()
    proposed = _call(
        MCP_TOOL_CALL_NAME,
        {"name": "mcp.fixture.echo", "arguments": {"value": "approved"}},
    )

    resolved = catalog.resolve(proposed)

    assert resolved.tool_call_id == proposed.tool_call_id
    assert resolved.provider_call_id == proposed.provider_call_id
    assert resolved.name == "mcp.fixture.echo"
    assert resolved.arguments == {"value": "approved"}
    assert resolved.provider_tool_name == MCP_TOOL_CALL_NAME
    assert resolved.provider_arguments == proposed.arguments


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"name": "mcp.fixture.echo"}, "requires only name and arguments"),
        ({"name": "mcp.fixture.echo", "arguments": []}, "arguments must be an object"),
        ({"name": MCP_TOOL_CALL_NAME, "arguments": {}}, "cannot describe themselves"),
        ({"name": "mcp.fixture.missing", "arguments": {}}, "not authorized"),
    ],
)
def test_call_bridge_rejects_invalid_or_unselected_targets(
    arguments: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _active_catalog().resolve(_call(MCP_TOOL_CALL_NAME, arguments))


def _active_catalog() -> AuthorizedMcpToolCatalog:
    return AuthorizedMcpToolCatalog(
        tuple(_definition(f"mcp.fixture.echo{index if index else ''}") for index in range(4)),
        threshold_bytes=1,
    )


def _definition(name: str) -> ModelToolDefinition:
    return ModelToolDefinition(
        name=name,
        description="Echo one value from the fixture MCP server.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        provider_call_id="call_provider",
    )

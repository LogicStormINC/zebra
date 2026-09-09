import json

import pytest
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog

from tests.api.test_extension_reads import MCP


def tool(name="search", schema='{"type":"object"}'):
    return McpCatalogTool(name=name, input_schema_json=schema)


def catalog(**updates):
    return McpToolCatalog(connection=MCP, protocol_version="2025-11-25", tools=(tool(),), **updates)


def test_canonical_immutable_catalog():
    a = McpToolCatalog(connection=MCP, protocol_version="2025-11-25", tools=(tool("b"), tool("a")))
    b = McpToolCatalog(connection=MCP, protocol_version="2025-11-25", tools=(tool("a"), tool("b")))
    assert a == b and a.digest == b.digest
    schema = json.loads(a.tools[0].input_schema_json)
    schema["type"] = "string"
    assert a == b
    with pytest.raises(ValueError):
        a.tools[0].name = "changed"


@pytest.mark.parametrize(
    "schema",
    [
        "[]",
        "{}",
        '{"type":"array"}',
        '{"type":"object","type":"object"}',
        '{"type":"object","x":NaN}',
        '{"type":"object","x":Infinity}',
        "not-json",
        '{"type":"object","x":{"a":1,"a":2}}',
    ],
)
def test_invalid_schema(schema):
    with pytest.raises(ValueError):
        tool(schema=schema)


def test_digest_binds_contract_and_identity():
    original = catalog()
    for changed in (
        original.model_copy(update={"protocol_version": "2025-06-18"}),
        original.model_copy(update={"connection": MCP.model_copy(update={"revision": 2})}),
        original.model_copy(update={"tools": (tool("different"),)}),
    ):
        assert original.digest != changed.digest


def test_duplicate_and_size_limits():
    with pytest.raises(ValueError, match="duplicate"):
        McpToolCatalog(connection=MCP, protocol_version="v1", tools=(tool(), tool()))
    with pytest.raises(ValueError):
        tool(schema=json.dumps({"type": "object", "description": "x" * 65536}))
    with pytest.raises(ValueError):
        McpToolCatalog(
            connection=MCP, protocol_version="v1", tools=tuple(tool(str(i)) for i in range(257))
        )
    large = tuple(
        McpCatalogTool(name=str(i), description="x" * 8192, input_schema_json='{"type":"object"}')
        for i in range(130)
    )
    with pytest.raises(ValueError, match="byte limit"):
        McpToolCatalog(connection=MCP, protocol_version="v1", tools=large)

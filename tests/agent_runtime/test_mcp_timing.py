"""Offline phase accounting must not alter MCP wire or disclose request data."""

import json
import logging

import pytest
from agent_core.domain.extension_snapshots import (
    ExtensionPermissions,
    ExtensionSnapshot,
    McpSnapshotEntry,
)
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_runtime.cloud_mcp_transport import CloudMcpTransport

from tests.agent_runtime import test_cloud_mcp_transport as http_fixtures
from tests.agent_runtime import test_mcp_sse as sse_fixtures
from tests.agent_runtime.test_cloud_mcp_transport import request, setup
from tests.agent_runtime.test_mcp_catalog_discovery import CONNECTION

wire = http_fixtures.wire
network = sse_fixtures.network


def assert_numeric_phases(metadata, expected):
    phases = metadata["mcp_timings_ms"]
    assert expected <= phases.keys()
    assert all(type(value) is float and value >= 0 for value in phases.values())
    assert phases["total"] >= phases["initialize"]
    assert phases["total"] >= phases["tools_call"]
    assert "today" not in json.dumps(phases)


def test_http_phase_metadata_and_each_call_still_initializes(wire):
    checked = []
    transport, _, _ = setup(lambda entry, op, endpoint, frame: checked.append(frame["method"]))
    expected = {"total", "initialize", "initialized_notify", "tools_call",
                "authorization", "dns_ssrf", "http_post", "initialize_result_wait",
                "tools_call_result_wait"}
    for _ in range(2):
        response = transport.execute(request(transport))
        assert "matched event" in response.output
        assert_numeric_phases(response.metadata, expected)
    assert checked == ["initialize", "notifications/initialized", "tools/call"] * 2
    assert len(wire) == 6  # no session reuse or discovery introduced


def test_sse_phase_metadata_preserves_wire_and_cleanup(network):
    from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog

    sent, streams, result = network
    result.clear()
    result.update({"content": [{"type": "text", "text": "actual result"}]})
    connection = CONNECTION.model_copy(update={"transport": "sse", "enabled": True})
    catalog = McpToolCatalog(connection=connection, protocol_version="2024-11-05",
                            tools=(McpCatalogTool(name="fetch", description="Fetch",
                                   input_schema_json='{"type":"object"}'),))
    entry = McpSnapshotEntry(connection=connection, catalog_digest=catalog.digest,
                            permissions=ExtensionPermissions(tools=("fetch",)))
    snapshot = ExtensionSnapshot(scope=connection.scope, session_id="session", turn_id="turn",
                                 mcp=(entry,))
    checked = []
    transport = CloudMcpTransport(snapshot, (catalog,),
                                 authorize=lambda e, o, u, f: checked.append(f["method"]))
    for _ in range(2):
        response = transport.execute(request(transport, {"url": "https://example.test/"}))
        assert "actual result" in response.output
        assert_numeric_phases(response.metadata, {"total", "initialize", "initialized_notify",
                              "tools_call", "authorization", "sse_open", "sse_endpoint_wait",
                              "http_post", "initialize_result_wait", "tools_call_result_wait"})
    assert [req.method for req in sent] == ["GET", "POST", "POST", "POST"] * 2
    assert checked == ["initialize", "initialize", "notifications/initialized", "tools/call"] * 2
    assert all(stream.closed for stream in streams)


def test_failure_timings_are_numeric_and_do_not_mask_revocation(wire, caplog):
    def authorize(*args):
        raise PluginAuthorityUnavailable("private-secret-body")

    transport, _, _ = setup(authorize)
    with caplog.at_level(logging.WARNING), pytest.raises(PluginAuthorityUnavailable):
        transport.execute(request(transport))
    assert wire == []
    assert "cloud_mcp_timing status=failed" in caplog.text
    assert "private-secret-body" not in caplog.text
    assert CONNECTION.endpoint not in caplog.text


def test_nested_phase_accumulation_survives_exception_without_double_counting(monkeypatch):
    from agent_runtime.mcp_timing import mcp_phase

    ticks = iter([0.0, 0.1, 0.3, 0.5, 0.7, 1.0])
    monkeypatch.setattr("agent_runtime.mcp_timing.perf_counter", lambda: next(ticks))
    timings = {}
    with pytest.raises(RuntimeError, match="original"), mcp_phase(timings, "total"):
        with mcp_phase(timings, "authorization"):
            pass
        with mcp_phase(timings, "authorization"):
            raise RuntimeError("original")
    assert timings == pytest.approx({"total": 1000.0, "authorization": 400.0})

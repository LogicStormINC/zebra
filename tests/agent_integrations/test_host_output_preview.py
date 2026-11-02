"""Exact-prefix Host summaries retain their full evidence through the existing projector."""

import pytest
from agent_integrations.host_tools import (
    HostToolGateway,
    HostToolManifest,
    HostToolTransportResponse,
    HostWorkloadIdentity,
)
from agent_tools.output_projection import ToolOutputProjector

from tests.agent_integrations.test_host_tools import (
    _context,
    _FakeTransport,
    _tool_call,
    _tool_payload,
)


def invoke(preview, configured=True):
    full = '{"metadata_only":true}\n\nFULL ORIGINAL\n' + "evidence 😀" * 3000
    captured = {}

    def persist(content, name):
        captured[name] = content
        return "artifact://original"

    transport = _FakeTransport(
        [HostToolTransportResponse(200, {"output": full, "model_preview": preview})]
    )
    tool = {**_tool_payload(), "maxOutputBytes": 262144}
    manifest = HostToolManifest.from_payload({"workloadIdentity": "trench-worker", "tools": [tool]})
    gateway = HostToolGateway(
        "https://trench.example",
        HostWorkloadIdentity("trench-worker", "tenant-1", "trench"),
        transport=transport,
        output_projector=ToolOutputProjector(persist) if configured else None,
    )
    return (
        gateway.invoke(_tool_call(), _context(), idempotency_key="one", manifest=manifest),
        captured,
        full,
    )


def test_prefix_is_small_but_original_is_preserved_and_coverage_is_exact():
    preview = '{"metadata_only":true}'
    result, captured, full = invoke(preview)
    assert list(captured.values()) == [full]
    assert result.output == preview + "\n\n[Complete output: artifact://original]"
    assert result.metadata["output_coverage"]["included_ranges"] == [[0, len(preview)]]
    assert result.metadata["output_envelope"]["retained_bytes"] == len(full.encode())
    assert result.receipt.output_bytes == len(full.encode())


@pytest.mark.parametrize("preview", [None, False, "invented fact", "x" * 12001])
def test_invalid_preview_does_not_change_output_or_manufacture_evidence(preview):
    result, captured, full = invoke(preview)
    assert result.output == full and captured == {}


def test_no_projector_keeps_original_behavior():
    result, captured, full = invoke('{"metadata_only":true}', False)
    assert result.output == full and not captured

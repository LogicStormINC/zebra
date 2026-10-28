"""Service tools do not depend on OCI availability; workspace tools still do."""
import asyncio
from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.session_history import SessionHistoryResult
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.ports.runtime import RuntimeCapabilityError
from agent_runtime import LocalToolGateway
from agent_runtime.deferred import DeferredRuntime


def call(tool_name, **arguments):
    return ToolCall(tool_call_id=new_tool_call_id(), name=tool_name, arguments=arguments,
                    created_at=datetime.now(UTC))


class History:
    def __init__(self):
        self.requests = []

    def query(self, request):
        self.requests.append(request)
        return SessionHistoryResult(mode=request.mode)


def test_service_reads_and_control_markers_do_not_prepare_runtime(tmp_path):
    prepared = []
    def prepare():
        prepared.append(True)
        raise RuntimeCapabilityError("missing pinned image")
    history = History()
    runtime = DeferredRuntime(prepare)
    gateway = LocalToolGateway(tmp_path, runtime=runtime, session_history=history)
    try:
        result = gateway.execute(call("sessions.search", query="example"))
        assert result.status is ToolCallStatus.EXECUTED
        assert result.metadata["runtime_prepare_ms"] == 0
        assert len(history.requests) == 1
        assert gateway.execute(call("sessions.search", query="")).status is ToolCallStatus.FAILED
        for name, args in (("agent.plan", {}), ("agent.clarify", {"question": "Which?"})):
            result = gateway.execute(call(name, **args))
            assert result.status is ToolCallStatus.FAILED  # Harness-only control, never bypassed.
            assert "requires_harness" in result.metadata["reason"]
        assert prepared == []
        with pytest.raises(RuntimeCapabilityError, match="missing pinned image"):
            gateway.execute(call("files.list"))
        assert prepared == [True]
    finally:
        gateway.close()
        runtime.close()


def test_cancelled_history_read_never_reads_or_prepares(tmp_path):
    def stopped():
        raise asyncio.CancelledError()
    def forbidden():
        raise AssertionError("must not prepare")
    history = History()
    runtime = DeferredRuntime(forbidden)
    gateway = LocalToolGateway(tmp_path, runtime=runtime, session_history=history,
                               network_cancellation_check=stopped)
    try:
        with pytest.raises(asyncio.CancelledError):
            gateway.execute(call("sessions.search"))
        assert history.requests == []
    finally:
        gateway.close()
        runtime.close()


def test_authorized_catalog_reads_skip_sandbox_but_do_not_invoke_mcp(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agent_core.domain.modeling import ModelToolDefinition
    from agent_runtime import harness
    def forbidden(*args, **kwargs):
        raise AssertionError("no sandbox or transport call for catalog reads")
    transport = SimpleNamespace(model_tools=(ModelToolDefinition(
        name="mcp.demo.read", description="bounded read " + "x" * 9000,
        parameters={"type": "object", "properties": {}}),), close=lambda: None)
    monkeypatch.setattr(harness, "build_mcp_transport", lambda *a, **kw: transport)
    runtime = DeferredRuntime(forbidden)
    gateway = LocalToolGateway(tmp_path, runtime=runtime)
    try:
        result = gateway.execute(call("agent.tools.search", query="read"))
        assert result.status is ToolCallStatus.EXECUTED
        result = gateway.execute(call("agent.tools.describe", name="mcp.demo.read"))
        assert result.status is ToolCallStatus.EXECUTED
        result = gateway.execute(call("agent.tools.describe", name="mcp.other.secret"))
        assert result.status is ToolCallStatus.FAILED
    finally:
        gateway.close()
        runtime.close()

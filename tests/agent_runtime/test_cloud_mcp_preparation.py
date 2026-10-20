"""Remote Cloud MCP needs live authority, not an unrelated local sandbox."""

import pytest
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.deferred import DeferredRuntime
from agent_runtime.harness import LocalToolGateway

from tests.agent_runtime import test_cloud_mcp_transport as fixtures
from tests.agent_runtime.test_cloud_mcp_transport import setup
from tests.agent_runtime.test_mcp_stdio import _tool_call

wire = fixtures.wire


def test_selected_cloud_mcp_skips_prepare_but_workspace_still_requires_it(tmp_path, wire):
    prepared = []
    runtime = LocalRuntime()

    def prepare():
        prepared.append(True)
        return runtime, runtime.provision(workspace_root=str(tmp_path))

    deferred = DeferredRuntime(prepare)
    transport, _, _ = setup()
    gateway = LocalToolGateway(tmp_path, runtime=deferred, cloud_mcp_transport=transport)
    try:
        result = gateway.execute(_tool_call(transport.model_tools[0].name, {"query": "today"}))
        assert result.status.value == "executed"
        assert prepared == []
        assert result.metadata["runtime_prepare_ms"] == 0
        assert len(wire) == 3
        (tmp_path / "sample.txt").write_text("local content")
        result = gateway.execute(_tool_call("files.read", {"path": "sample.txt"}))
        assert result.status.value == "executed", result
        assert prepared == [True]
        assert result.metadata["runtime_prepare_ms"] >= 0
    finally:
        gateway.close()
        deferred.close()


@pytest.mark.parametrize("boundary", ["cancel", "plugin", "arguments"])
def test_cloud_skip_never_bypasses_cancellation_revocation_or_arguments(tmp_path, wire, boundary):
    prepared = []

    def prepare():
        prepared.append(True)
        raise AssertionError("must not provision for Cloud MCP")

    def check():
        if boundary == "cancel":
            raise RuntimeError("cancelled")

    def authorize(*args):
        if boundary == "plugin":
            raise PluginAuthorityUnavailable("revoked")

    deferred = DeferredRuntime(prepare)
    transport, _, _ = setup(authorize)
    gateway = LocalToolGateway(tmp_path, runtime=deferred, cloud_mcp_transport=transport,
                               network_cancellation_check=check)
    call = _tool_call(transport.model_tools[0].name,
                      {"unknown": "value"} if boundary == "arguments" else {"query": "today"})
    try:
        if boundary == "arguments":
            assert gateway.execute(call).status.value == "failed"
        else:
            error = RuntimeError if boundary == "cancel" else PluginAuthorityUnavailable
            with pytest.raises(error):
                gateway.execute(call)
        assert prepared == []
        assert wire == []
    finally:
        gateway.close()
        deferred.close()


@pytest.mark.parametrize("cloud", [False, True])
def test_noncloud_and_spoofed_aliases_keep_preparation(tmp_path, wire, monkeypatch, cloud):
    prepared = []
    transport, _, _ = setup()
    if not cloud:
        monkeypatch.setattr("agent_runtime.harness.build_mcp_transport", lambda *a, **k: transport)

    def prepare():
        prepared.append(True)
        raise RuntimeError("sandbox unavailable")

    deferred = DeferredRuntime(prepare)
    gateway = LocalToolGateway(tmp_path, runtime=deferred,
                               cloud_mcp_transport=transport if cloud else None)
    name = "mcp.spoofed.alias" if cloud else transport.model_tools[0].name
    try:
        with pytest.raises(RuntimeError, match="sandbox unavailable"):
            gateway.execute(_tool_call(name, {"query": "today"}))
        assert prepared == [True]
        assert wire == []
    finally:
        gateway.close()
        deferred.close()

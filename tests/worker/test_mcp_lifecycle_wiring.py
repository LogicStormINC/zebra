from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.domain.extension_snapshots import ExtensionPermissions, McpSnapshotEntry
from zebra_agent_worker.execution_tool_gateway import build_execution_tool_gateway, extensions
from zebra_agent_worker.extension_recovery import recover_turn_extension

from tests.agent_runtime.test_mcp_stdio import _tool_call
from tests.worker import test_extension_recovery as recovery
from tests.worker import test_mcp_composition as startup
from tests.worker import test_worker_mcp_catalog as catalog
from tests.worker.test_cloud_context_materialization import _task

mounted = startup.mounted
protector = catalog.protector
wire = catalog.wire


@pytest.mark.parametrize("selected", [False, True])
def test_execution_gateway_exposes_and_executes_selected_mcp(
    tmp_path, mounted, protector, wire, selected,
):
    callback, source, extension = catalog.setup(tmp_path, protector)
    settings = replace(
        mounted, mcp_credentials=replace(mounted.mcp_credentials, worker_enabled=True),
        mcp_servers=(SimpleNamespace(name="must-not-use-process-server"),),
    )
    if not selected:
        extension = replace(extension, snapshot=extension.snapshot.model_copy(update={"mcp": ()}))
    service = SimpleNamespace(
        _settings=settings, _session_history=Mock(), _artifact_payload_store=None,
        _egress_registry=None, _delegation_store=None, _deployment_namespace="test",
        _frozen_manifest_loader=None, _client_runtime=None,
        _extensions=extensions(Mock(), None, source),
    )
    gateway = build_execution_tool_gateway(
        service, task=_task(tmp_path), model_gateway=Mock(), session_id=callback.session_id,
        runtime=Mock(), runtime_handle=Mock(), cloud_artifacts=None, trusted_local=False,
        task_binding=None, materialized_context=None, extension=extension, fence=callback.fence,
    )
    try:
        assert wire == []
        assert len(gateway.effective_mcp_tools) == int(selected)
        if not selected:
            source.catalogs.get.assert_not_called()
            return
        result = gateway.execute(_tool_call(gateway.effective_mcp_tools[0].name, {}))
        assert result.status.value == "executed", result
        assert "matched event" in result.output
        assert wire[-1][0]["method"] == "tools/call"
    finally:
        gateway.close()


def test_recovery_mcp_gate_requires_explicit_worker_composition(tmp_path, protector):
    _, source, extension = catalog.setup(tmp_path, protector)
    snapshot, ceiling, events = recovery._fixtures()
    connection = extension.snapshot.mcp[0].connection.model_copy(update={"scope": snapshot.scope})
    entry = McpSnapshotEntry(
        connection=connection, catalog_digest="a" * 64,
        permissions=ExtensionPermissions(tools=("search",)),
    )
    snapshot = snapshot.model_copy(update={"mcp": (entry,)})
    events[0] = events[0].model_copy(update={
        "payload": events[0].payload | {"extension_snapshot_digest": snapshot.digest},
    })
    store = recovery._Store(snapshot, ceiling)
    args = dict(store=store, events=events, session_id=recovery.SESSION_ID,
                task_binding=ceiling.binding)
    with pytest.raises(ValueError, match="MCP snapshots"):
        recover_turn_extension(**args)
    recovered = recover_turn_extension(**args, allow_mcp=True)
    assert recovered.snapshot.mcp == (entry,)
    source.catalogs.get.assert_not_called()
    with pytest.raises(ValueError, match="recovery"):
        extensions(None, None, source)

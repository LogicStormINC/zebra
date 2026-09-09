from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionRequest
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_core.ports.mcp_catalog import McpCatalogStore
from agent_runtime.mcp_protocol import McpProtocolError
from agent_security.mcp_execution_authority import McpWorkerAuthority
from agent_tools import McpProxyRequest, McpToolTarget
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
from zebra_agent_worker.extension_recovery import RecoveredTurnExtension
from zebra_agent_worker.worker_mcp_catalog import WorkerMcpSource, prepare_worker_mcp

from tests.agent_runtime import test_cloud_mcp_transport as transport_fixtures
from tests.agent_runtime import test_mcp_anonymous_execution as authority

protector = authority.protector
wire = transport_fixtures.wire


def worker_authority(callback):
    ceiling = callback.release.tasks.resolve_task_ceiling.return_value
    binding = ceiling.binding.model_copy(update={
        "host_capability": ceiling.binding.host_capability.model_copy(update={
            "grant_expires_at": ceiling.binding.host_capability.host_context.expires_at,
        }),
    })
    callback.release.tasks.resolve_task_ceiling.return_value = ceiling.model_copy(
        update={"binding": binding}
    )
    resolver = BoundHostExecutionAuthorityResolver(binding=binding)
    snapshot = resolver.resolve_for_attempt(ExecutionAuthorityResolutionRequest(
        session_id=callback.session_id, attempt_number=1, scope=resolver.scope,
        validated_at=datetime.now(UTC),
    ))
    return McpWorkerAuthority(str(callback.session_id), snapshot)


def setup(tmp_path, protector):
    callback = authority.anonymous(tmp_path, protector)
    evidence = worker_authority(callback)
    snapshot = callback.release.snapshots.get.return_value
    entry = snapshot.mcp[0]
    catalog = McpToolCatalog(
        connection=entry.connection,
        protocol_version="2025-11-25",
        tools=(McpCatalogTool(name="search", input_schema_json='{"type":"object"}'),),
    )
    snapshot = snapshot.model_copy(
        update={"mcp": (entry.model_copy(update={"catalog_digest": catalog.digest}),)}
    )
    callback.release.snapshots.get.return_value = snapshot
    catalogs = AsyncMock(spec=McpCatalogStore)
    catalogs.get.return_value = catalog
    source = WorkerMcpSource(
        catalogs,
        callback.connections,
        callback.release,
        callback.leases,
        lambda session, turn: evidence,
    )
    extension = RecoveredTurnExtension(
        snapshot.scope, snapshot, callback.release.tasks.resolve_task_ceiling.return_value
    )
    return callback, source, extension


def test_worker_catalog_to_live_authorized_http_call(tmp_path, protector, wire):
    callback, source, extension = setup(tmp_path, protector)
    transport = prepare_worker_mcp(
        extension, source=source, session_id=callback.session_id, fence=callback.fence
    )
    assert wire == []
    _, server, tool = transport.model_tools[0].name.split(".")
    result = transport.execute(McpProxyRequest("call", McpToolTarget(server, tool)))
    assert "matched event" in result.output
    assert wire[-1][0]["params"] == {"name": "search", "arguments": {}}
    assert source.connections.get_connection.await_count == 3
    source.release.store.get_for_use.assert_not_called()
    source.catalogs.get.assert_awaited_once_with(
        scope=extension.scope,
        connection_id="mcp",
        config_revision=extension.snapshot.mcp[0].connection.revision,
        expected_digest=extension.snapshot.mcp[0].catalog_digest,
    )


def test_worker_stale_fence_blocks_http(tmp_path, protector, wire):
    callback, source, extension = setup(tmp_path, protector)
    transport = prepare_worker_mcp(
        extension, source=source, session_id=callback.session_id, fence=callback.fence
    )
    callback.leases.release(callback.session_id, fence=callback.fence)
    _, server, tool = transport.model_tools[0].name.split(".")
    with pytest.raises(McpProtocolError):
        transport.execute(McpProxyRequest("call", McpToolTarget(server, tool)))
    assert wire == []


def test_worker_missing_source_rejected_before_catalog_read(tmp_path, protector):
    callback, source, extension = setup(tmp_path, protector)
    with pytest.raises(ValueError, match="not configured"):
        prepare_worker_mcp(
            extension, source=None, session_id=callback.session_id, fence=callback.fence
        )
    source.catalogs.get.assert_not_called()
    assert (
        prepare_worker_mcp(None, source=None, session_id=callback.session_id, fence=callback.fence)
        is None
    )

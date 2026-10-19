"""Native component sources retain their existing Cloud identity and checks."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_runtime.mcp_protocol import McpProtocolError
from agent_tools import McpProxyRequest, McpToolTarget
from agent_tools.cloud_skills import CloudSkillCatalog
from zebra_agent_worker.plugin_composition import compose_worker_plugins
from zebra_agent_worker.worker_mcp_catalog import prepare_worker_mcp
from zebra_agent_worker.worker_skill_catalog import (
    WorkerSkillCatalogSource,
    prepare_worker_skill_catalog,
)

from tests.worker.test_cloud_skill_wiring import Backend, _extension
from tests.worker.test_worker_mcp_catalog import protector, setup, wire

__all__ = ["protector", "wire"]


def test_worker_composition_has_no_bundle_mount_or_mcp_secret_requirement() -> None:
    off = SimpleNamespace(plugins=SimpleNamespace(enabled=False))
    assert compose_worker_plugins(off, None) is None
    settings = SimpleNamespace(
        plugins=SimpleNamespace(enabled=True),
        deployment="cloud",
        storage_authority="postgresql",
        cloud_extension_worker_enabled=True,
    )
    cloud = SimpleNamespace(
        dsn="postgresql://unused",
        deployment_namespace="plugins",
        extension_snapshots=Mock(),
        skill_objects=Mock(),
        stores=SimpleNamespace(task_io_connections=None),
    )
    source = compose_worker_plugins(settings, cloud)
    assert source.packages.objects is cloud.skill_objects
    assert not cloud.skill_objects.mock_calls


def test_guarded_skill_catalog_preserves_native_identity_and_authorization() -> None:
    backend, guard = Backend(), Mock()
    catalog = prepare_worker_skill_catalog(
        _extension(backend),
        deployment_namespace="test",
        source=WorkerSkillCatalogSource(backend, backend),
        plugin_guard=guard,
    )
    assert isinstance(catalog, CloudSkillCatalog)
    assert catalog.list()[0][0].name == "sample"
    assert guard.validate.call_count == 2 and backend.calls == ["authorization"]
    guard.validate.side_effect = PluginAuthorityUnavailable()
    with pytest.raises(PluginAuthorityUnavailable):
        catalog.read("sample")
    assert "object" not in backend.calls


def test_mcp_per_frame_plugin_stop_and_native_lease_priority(tmp_path, protector, wire) -> None:
    callback, source, extension = setup(tmp_path, protector)
    guard = Mock()
    guard.validate.side_effect = PluginAuthorityUnavailable()
    transport = prepare_worker_mcp(
        extension,
        source=source,
        session_id=callback.session_id,
        fence=callback.fence,
        plugin_guard=guard,
    )
    assert transport.model_tools
    _, server, tool = transport.model_tools[0].name.split(".")
    with pytest.raises(PluginAuthorityUnavailable):
        transport.execute(McpProxyRequest("call", McpToolTarget(server, tool)))
    assert wire == [] and guard.validate.call_count == 1
    guard.reset_mock()
    callback.leases.release(callback.session_id, fence=callback.fence)
    with pytest.raises(McpProtocolError):
        transport.execute(McpProxyRequest("call", McpToolTarget(server, tool)))
    guard.validate.assert_not_called()

"""Configured management tools participate in the ordinary Worker gateway."""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from agent_core.domain.tools import ToolCallStatus
from agent_core.ports.extensions import ExtensionStore, McpConnectionPage
from agent_runtime import LocalToolGateway
from agent_tools.extension_management import ExtensionManagementTools
from zebra_agent_worker.tool_gateway_runtime import WorkerToolGateway
from zebra_agent_worker.worker_extension_management import prepare_extension_management

from tests.agent_tools.test_extension_management import call
from tests.api.test_extension_reads import SCOPE


def test_management_catalog_policy_and_dispatch():
    local = Mock(spec=LocalToolGateway)
    local.model_tools = ()
    store = AsyncMock(spec=ExtensionStore)
    store.list_mcp.return_value = McpConnectionPage(items=())
    gateway = WorkerToolGateway(
        local=local, management=ExtensionManagementTools(store, lambda permission: SCOPE),
        management_names=frozenset({"extensions.list", "extensions.add_mcp"}),
    )
    assert {tool.name for tool in gateway.model_tools} == {
        "extensions.list", "extensions.add_mcp",
    }
    assert "extensions.list" in gateway.read_only_tools
    assert "extensions.add_mcp" not in gateway.read_only_tools
    assert gateway.authorized_write_tools == frozenset({"extensions.add_mcp"})
    assert not gateway.approval_required_tools
    result = gateway.execute(call("list", kind="mcp"))
    assert result.status == ToolCallStatus.EXECUTED
    assert json.loads(result.output) == {"items": [], "next_cursor": None}
    local.execute.assert_not_called()
    unregistered = call("refresh_mcp", connection_id="mcp", expected_revision=1)
    assert gateway.execute(unregistered) is local.execute.return_value
    local.execute.assert_called_once_with(unregistered)


def test_unconfigured_gateway_keeps_ordinary_catalog_and_dispatch():
    local = Mock(spec=LocalToolGateway)
    local.model_tools = ()
    gateway = WorkerToolGateway(local=local)
    assert gateway.model_tools == ()
    assert not gateway.authorized_write_tools
    assert "extensions.list" not in gateway.read_only_tools
    request = call("list", kind="mcp")
    assert gateway.execute(request) is local.execute.return_value
    local.execute.assert_called_once_with(request)


def test_worker_web_catalog_hides_networked_tools_without_web_authority(tmp_path):
    local = LocalToolGateway(tmp_path.resolve(), web_pipeline_v2=True)
    blocked = WorkerToolGateway(local=local, web_egress_enabled=False, web_pipeline_v2=True)
    allowed = WorkerToolGateway(local=local, web_egress_enabled=True, web_pipeline_v2=True)
    assert not {tool.name for tool in blocked.model_tools} & {
        "web.fetch", "web.search", "web.crawl", "web.extract"
    }
    assert {"web.read", "web.find"} <= {tool.name for tool in blocked.model_tools}
    assert {"web.fetch", "web.crawl", "web.extract"} <= {
        tool.name for tool in allowed.model_tools
    }
    assert {"web.crawl", "web.extract", "web.read", "web.find"} <= blocked.read_only_tools


@pytest.mark.parametrize("allow_network", [False, True])
def test_worker_preparation_preserves_network_ceiling(allow_network):
    extension, mcp, skills = Mock(), Mock(), Mock()
    extension.scope = SCOPE
    context = extension.task_ceiling.binding.host_capability.host_context
    context.scopes = ("agent.run", "extensions.manage")
    prepared = prepare_extension_management(
        extension, mcp=mcp, skills=skills, session_id="session", fence=Mock(),
        allow_network=allow_network,
    )
    assert prepared is not None
    assert (prepared.refresh is not None) is allow_network
    assert (prepared.import_skill is not None) is allow_network
    mcp.execution_authority.assert_not_called()
    skills.store.assert_not_called()
    context.scopes = ("agent.run",)
    assert prepare_extension_management(
        extension, mcp=mcp, skills=skills, session_id="session", fence=Mock(),
        allow_network=allow_network,
    ) is None


def test_management_preparation_receives_the_real_snapshot_and_skill_catalog(monkeypatch):
    import zebra_agent_worker.worker_extension_management as composition

    extension, mcp, skills, catalog = Mock(), Mock(), Mock(), Mock()
    extension.scope = SCOPE
    extension.task_ceiling.binding.host_capability.host_context.scopes = ("extensions.read",)
    monkeypatch.setattr(composition, "ExtensionWorkerAuthority", lambda **kwargs: Mock())
    prepared = prepare_extension_management(
        extension, mcp=mcp, skills=skills, session_id="session", fence=Mock(),
        skill_catalog=catalog,
    )
    assert prepared is not None
    assert prepared.snapshot is extension.snapshot
    assert prepared.skill_catalog is catalog
    assert prepared.mcp_catalogs is mcp.catalogs
    assert prepared.refresh is None and prepared.import_skill is None
    assert not mcp.catalogs.mock_calls and not catalog.mock_calls


def test_execution_reuses_one_prepared_skill_catalog_for_management(monkeypatch):
    import zebra_agent_worker.execution_tool_gateway as composition

    service, task = Mock(), Mock()
    service._settings.deployment = "cloud"
    task.network_profile.name.value = "none"
    gateway, catalog = Mock(), Mock()
    build, prepare = Mock(return_value=gateway), Mock(return_value=catalog)
    management = Mock(return_value=None)
    monkeypatch.setattr(composition, "build_worker_tool_gateway", build)
    monkeypatch.setattr(composition.worker_skills, "prepare_worker_skill_catalog", prepare)
    monkeypatch.setattr(composition, "prepare_extension_management", management)
    monkeypatch.setattr(composition, "prepare_worker_plugins", Mock(return_value=None))
    monkeypatch.setattr(composition, "prepare_worker_mcp", Mock(return_value=None))
    composition.build_execution_tool_gateway(
        service, task=task, model_gateway=Mock(), session_id="session", runtime=Mock(),
        runtime_handle=None, cloud_artifacts=None, trusted_local=False, task_binding=None,
        materialized_context=None, extension=None, fence=Mock(),
    )
    prepare.assert_called_once()
    assert build.call_args.kwargs["skill_catalog"] is catalog
    assert management.call_args.kwargs["skill_catalog"] is catalog
    assert not management.call_args.kwargs["allow_network"]


def test_revoked_plugin_blocks_inventory_before_catalog_or_store(monkeypatch):
    import zebra_agent_worker.worker_extension_management as composition
    from agent_core.domain.plugin_authority import PluginAuthorityUnavailable

    extension, mcp, skills, guard = Mock(), Mock(), Mock(), Mock()
    extension.scope = SCOPE
    extension.task_ceiling.binding.host_capability.host_context.scopes = ("extensions.read",)
    monkeypatch.setattr(composition, "ExtensionWorkerAuthority",
                        lambda **kwargs: Mock(return_value=SCOPE))
    guard.validate.side_effect = PluginAuthorityUnavailable("private revocation details")
    prepared = prepare_extension_management(
        extension, mcp=mcp, skills=skills, session_id="session", fence=Mock(),
        plugin_guard=guard,
    )
    result = prepared.execute(call("list", kind="mcp"))
    assert result.output == "management_unavailable_or_not_authorized"
    guard.validate.assert_called_once()
    assert not mcp.catalogs.mock_calls and not skills.store.mock_calls

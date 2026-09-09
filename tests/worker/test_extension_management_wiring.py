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

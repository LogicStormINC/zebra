import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from agent_core.domain.extensions import McpConnection
from agent_core.ports.extensions import ExtensionRevisionConflictError
from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_runtime.mcp_protocol import McpProtocolError
from agent_security.extension_authority import extension_scope_from_grant
from agent_security.host_grant import HostGrantBindingError

from tests.agent_runtime import test_mcp_catalog_discovery as discovery
from tests.agent_security.test_extension_authority import _verified

network = discovery.network


def grant(scopes=None):
    result = _verified(scopes=scopes if scopes is not None else ["extensions.manage"])
    return replace(
        result,
        context=result.context.model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(minutes=5)}
        ),
    )


def setup():
    verified = grant()
    scope = extension_scope_from_grant(verified, permission="extensions.manage")
    connection = McpConnection(
        scope=scope, connection_id="mcp", revision=1, endpoint="https://example.test/mcp"
    )
    connections, catalogs = AsyncMock(), AsyncMock()
    connections.get_connection.return_value = connection
    return McpCatalogRefresh(connections, catalogs, Mock(), "dev"), verified, connection


def run(service, verified):
    return asyncio.run(service.refresh(verified=verified, connection_id="mcp", expected_revision=1))


def test_authorized_refresh(network):
    service, verified, connection = setup()
    catalog = run(service, verified)
    assert catalog.connection == connection
    service.catalogs.publish.assert_awaited_once_with(scope=connection.scope, catalog=catalog)
    assert service.connections.get_connection.await_count == 5
    service.connections.get_for_use.assert_not_called()


@pytest.mark.parametrize("scopes", [["extensions.read"], ["agent.run"]])
def test_no_management_no_io(network, scopes):
    service, _, _ = setup()
    with pytest.raises(HostGrantBindingError):
        run(service, grant(scopes))
    assert service.connections.mock_calls == [] and network[0] == []


def test_expired_grant_no_io(network):
    service, verified, _ = setup()
    verified = replace(
        verified, context=verified.context.model_copy(update={"expires_at": datetime.now(UTC)})
    )
    with pytest.raises(HostGrantBindingError):
        run(service, verified)
    assert network[0] == []


@pytest.mark.parametrize("check_number", [1, 2, 3, 4, 5])
def test_config_change_blocks_frame_or_publication(network, check_number):
    service, verified, connection = setup()
    changed = connection.model_copy(update={"revision": 2})
    service.connections.get_connection.side_effect = [connection] * (check_number - 1) + [changed]
    with pytest.raises((ExtensionRevisionConflictError, McpProtocolError)):
        run(service, verified)
    service.catalogs.publish.assert_not_called()
    assert len(network[0]) == max(0, check_number - 2)


def test_discovery_error_preserves_catalog(network):
    service, verified, _ = setup()
    network[1][:] = [{"tools": [discovery.tool(), discovery.tool()]}]
    with pytest.raises(McpProtocolError):
        run(service, verified)
    service.catalogs.publish.assert_not_called()

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from agent_core.domain.extensions import McpConnection
from agent_core.ports.mcp_credentials import McpCredentialManagementStore
from agent_runtime.mcp_http import McpHttpSession
from agent_runtime.mcp_protocol import McpProtocolError

from tests.agent_runtime import test_mcp_execution_authorization as fixtures

protector = fixtures.protector
requests = fixtures.requests


def anonymous(tmp_path, protector):
    callback = fixtures.resolver(tmp_path, protector)
    snapshot = callback.release.snapshots.get.return_value
    entry = snapshot.mcp[0]
    connection = McpConnection.model_validate(
        entry.connection.model_dump()
        | {"auth_mode": "none", "auth_state": "not_required", "credential_ref": None}
    )
    snapshot = snapshot.model_copy(
        update={"mcp": (entry.model_copy(update={"connection": connection}),)}
    )
    callback.release.snapshots.get.return_value = snapshot
    connections = AsyncMock(spec=McpCredentialManagementStore)
    connections.get_connection.return_value = connection
    return replace(callback, snapshot_digest=snapshot.digest, connections=connections)


def execute(callback):
    with McpHttpSession(
        fixtures.Server(), 1, frame_authorizer=callback.authorize_anonymous
    ) as session:
        session.request("tools/call", {"name": "search", "arguments": {}})


def test_anonymous_checks_each_frame_without_releasing_secrets(tmp_path, protector, requests):
    callback = anonymous(tmp_path, protector)
    execute(callback)
    assert len(requests) == 3
    assert callback.connections.get_connection.await_count == 3
    callback.release.store.get_for_use.assert_not_called()


@pytest.mark.parametrize("change", ["disabled", "wrong_user", "revision", "missing_authority"])
def test_anonymous_live_changes_stop_send(tmp_path, protector, requests, change):
    callback = anonymous(tmp_path, protector)
    connection = callback.connections.get_connection.return_value
    if change == "missing_authority":
        callback = replace(callback, connections=None)
    else:
        updates = (
            {"enabled": False}
            if change == "disabled"
            else {"revision": 99}
            if change == "revision"
            else {"scope": connection.scope.model_copy(update={"principal_id": "other"})}
        )
        callback.connections.get_connection.return_value = connection.model_copy(update=updates)
    with pytest.raises(McpProtocolError):
        execute(callback)
    assert requests == []
    callback.release.store.get_for_use.assert_not_called()


def test_lease_loss_during_anonymous_lookup_stops_send(tmp_path, protector, requests):
    callback = anonymous(tmp_path, protector)
    connection = callback.connections.get_connection.return_value

    async def lookup(**kwargs):
        callback.leases.release(callback.session_id, fence=callback.fence)
        return connection

    callback.connections.get_connection.side_effect = lookup
    with pytest.raises(McpProtocolError):
        execute(callback)
    assert requests == []


def test_anonymous_cannot_call_other_tool(tmp_path, protector, requests):
    callback = anonymous(tmp_path, protector)
    with pytest.raises(McpProtocolError):
        callback.authorize_anonymous(
            callback.endpoint, {"method": "tools/call", "params": {"name": "other"}}
        )
    assert requests == []
    callback.connections.get_connection.assert_not_called()

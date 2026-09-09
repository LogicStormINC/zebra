import json
from dataclasses import replace
from datetime import timedelta

import pytest
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.leases import LeaseLostError
from agent_runtime.mcp_execution_authorization import McpExecutionCredentialResolver
from agent_runtime.mcp_http import McpHttpSession
from agent_runtime.mcp_protocol import McpProtocolError
from agent_storage.leases import SQLiteLeaseStore

from tests.agent_runtime import test_mcp_http_authorization as http_fixtures
from tests.agent_storage import test_mcp_credential_release as fixtures

protector = fixtures.protector
requests = http_fixtures.requests
Server = http_fixtures.Server


def resolver(tmp_path, protector):
    service, args, snapshot = fixtures.runtime(protector)
    session_id = new_session_id()
    snapshot = snapshot.model_copy(update={"session_id": str(session_id)})
    service.snapshots.get.return_value = snapshot
    leases = SQLiteLeaseStore(tmp_path / "lease.db")
    lease = leases.acquire(session_id, owner_instance_id="worker", ttl=timedelta(minutes=5))
    callback = McpExecutionCredentialResolver(
        release=service,
        leases=leases,
        fresh_authority=lambda: args["verified"],
        session_id=session_id,
        turn_id=snapshot.turn_id,
        snapshot_digest=snapshot.digest,
        fence=lease.fence,
        connection_id="mcp",
        endpoint=Server().url,
        method="tools/call",
        params_json='{"name":"search","arguments":{}}',
    )
    return callback


def test_real_lease_and_internal_release_authorize_each_http_frame(tmp_path, protector, requests):
    callback = resolver(tmp_path, protector)
    with McpHttpSession(Server(), 1, credential_resolver=callback) as session:
        session.request("tools/call", {"name": "search", "arguments": {}})
    assert len(requests) == 3
    assert callback.release.store.get_for_use.call_count == 3


@pytest.mark.parametrize("change", ["released", "stolen", "expired"])
def test_stale_lease_cannot_release_or_send(tmp_path, protector, requests, change):
    callback = resolver(tmp_path, protector)
    if change == "expired":
        lease = callback.leases.get(callback.session_id)
        from datetime import UTC, datetime
        from unittest.mock import Mock

        callback = replace(
            callback,
            leases=Mock(
                get=Mock(
                    return_value=lease.model_copy(
                        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                    )
                )
            ),
        )
    else:
        callback.leases.release(callback.session_id, fence=callback.fence)
        if change == "stolen":
            callback.leases.acquire(
                callback.session_id, owner_instance_id="other", ttl=timedelta(minutes=5)
            )
    with pytest.raises(McpProtocolError, match="authorization failed"):
        McpHttpSession(Server(), 1, credential_resolver=callback).request(
            "tools/call", {"name": "search", "arguments": {}}
        )
    assert requests == []
    callback.release.store.get_for_use.assert_not_called()


def test_lease_lost_while_awaiting_credential_stops_send(tmp_path, protector, requests):
    callback = resolver(tmp_path, protector)
    record = callback.release.store.get_for_use.return_value

    async def lose(**kwargs):
        callback.leases.release(callback.session_id, fence=callback.fence)
        return record

    callback.release.store.get_for_use.side_effect = lose
    with pytest.raises(McpProtocolError, match="authorization failed"):
        McpHttpSession(Server(), 1, credential_resolver=callback).request("initialize")
    assert requests == []


@pytest.mark.parametrize(
    "method,params",
    [
        ("tools/list", {}),
        ("tools/call", {"name": "delete"}),
        ("tools/call", {"name": "search", "arguments": {"extra": True}}),
        ("resources/read", {"uri": "document"}),
    ],
)
def test_operation_substitution_fails_before_release(tmp_path, protector, method, params):
    callback = resolver(tmp_path, protector)
    with pytest.raises(McpProtocolError, match="authorized operation"):
        callback(Server().url, {"method": method, "params": params})
    callback.release.store.get_for_use.assert_not_called()


@pytest.mark.parametrize(
    "method,params",
    [
        ("resources/read", {"uri": "document"}),
        ("prompts/get", {"name": "summary"}),
    ],
)
def test_resources_and_prompts_use_their_own_permissions(tmp_path, protector, method, params):
    callback = replace(resolver(tmp_path, protector), method=method, params_json=json.dumps(params))
    assert callback(Server().url, {"method": method, "params": params}).secret.value


def test_endpoint_change_and_released_lease_fail_directly(tmp_path, protector):
    callback = resolver(tmp_path, protector)
    with pytest.raises(McpProtocolError, match="endpoint mismatch"):
        callback("https://other.test/mcp", {"method": "initialize"})
    callback.leases.release(callback.session_id, fence=callback.fence)
    with pytest.raises(LeaseLostError):
        callback(Server().url, {"method": "initialize"})


def test_valid_token_cannot_be_relabelled_for_a_different_endpoint(tmp_path, protector):
    from agent_security.host_grant import HostGrantBindingError

    callback = replace(resolver(tmp_path, protector), endpoint="https://other.test/mcp")
    with pytest.raises(HostGrantBindingError, match="target endpoint mismatch"):
        callback("https://other.test/mcp", {"method": "initialize"})
    callback.release.store.get_for_use.assert_not_called()

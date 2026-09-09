"""Verified management authority and atomic PostgreSQL credential publication."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_security.extension_authority import extension_scope_from_grant
from agent_security.host_grant import HostGrantBindingError
from agent_security.mcp_credential_management import McpCredentialManagement
from agent_storage.postgres.extensions import PostgresExtensionStore

from tests.agent_security.test_extension_authority import _verified
from tests.agent_storage import test_postgres_mcp_credentials as fixtures

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
protector = fixtures.protector
TOKEN = fixtures.TOKEN


def management(dsn, protector):
    verified = _verified()
    scope = extension_scope_from_grant(verified, permission="extensions.manage")
    store = fixtures.setup(dsn, scope=scope)
    return McpCredentialManagement(store, protector, "dev"), store, verified, scope


@pytest.mark.parametrize("scopes", [[], ["agent.run"], ["extensions.read"]])
@pytest.mark.parametrize("action", ["provision", "revoke"])
def test_only_management_permission_can_write(scopes, action):
    store = AsyncMock()
    service = McpCredentialManagement(store, Mock(), "dev")
    args = {
        "verified": _verified(scopes=scopes) if scopes else None,
        "connection_id": "mcp",
        "expected_connection_revision": 1,
    }
    if action == "provision":
        args["token"] = TOKEN
    with pytest.raises(HostGrantBindingError):
        asyncio.run(getattr(service, action)(**args))
    assert store.mock_calls == []


def test_provision_rotate_revoke_keeps_ciphertext_history(dsn, protector):
    service, store, verified, scope = management(dsn, protector)
    first = asyncio.run(
        service.provision(
            verified=verified, connection_id="mcp", expected_connection_revision=1, token=TOKEN
        )
    )
    assert first.revision == 2 and first.auth_state.value == "ready"
    assert not first.enabled  # Provisioning does not silently enable a connection.
    encrypted = asyncio.run(
        store.get(scope=scope, connection_id="mcp", credential_ref=first.credential_ref)
    )
    assert protector.unseal(encrypted.binding, encrypted.envelope).value == TOKEN
    second = asyncio.run(
        service.provision(
            verified=verified,
            connection_id="mcp",
            expected_connection_revision=2,
            token="rotated-fixture-token",
        )
    )
    assert second.credential_ref != first.credential_ref
    assert TOKEN not in first.model_dump_json() + repr(service)
    revoked = asyncio.run(
        service.revoke(verified=verified, connection_id="mcp", expected_connection_revision=3)
    )
    assert revoked.revision == 4 and revoked.auth_state.value == "revoked" and not revoked.enabled
    current = asyncio.run(store.get_connection(scope=scope, connection_id="mcp"))
    assert current == revoked
    assert (
        asyncio.run(
            store.get(scope=scope, connection_id="mcp", credential_ref=first.credential_ref)
        )
        == encrypted
    )


def test_cross_user_cannot_manage_connection(dsn, protector):
    service, _, _, _ = management(dsn, protector)
    foreign = _verified(sub="other", resource_refs=[{"type": "principal", "id": "other"}])
    with pytest.raises(ExtensionNotFoundError):
        asyncio.run(
            service.provision(
                verified=foreign, connection_id="mcp", expected_connection_revision=1, token=TOKEN
            )
        )
    with pytest.raises(ExtensionNotFoundError):
        asyncio.run(
            service.revoke(verified=foreign, connection_id="mcp", expected_connection_revision=1)
        )


def test_failure_after_cipher_insert_rolls_back_both(dsn, protector, monkeypatch):
    service, store, verified, scope = management(dsn, protector)

    def fail(*args):
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr("agent_storage.postgres.mcp_credentials._write_connection", fail)
    with pytest.raises(RuntimeError, match="injected"):
        asyncio.run(
            service.provision(
                verified=verified, connection_id="mcp", expected_connection_revision=1, token=TOKEN
            )
        )
    assert asyncio.run(store.get_connection(scope=scope, connection_id="mcp")).revision == 1
    with store.connect() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM mcp_credential_versions").fetchone()["n"]
            == 0
        )


def test_concurrent_publish_has_one_complete_winner(dsn, protector):
    service, store, verified, scope = management(dsn, protector)

    async def race():
        return await asyncio.gather(
            *[
                service.provision(
                    verified=verified,
                    connection_id="mcp",
                    expected_connection_revision=1,
                    token=TOKEN,
                )
                for _ in range(2)
            ],
            return_exceptions=True,
        )

    results = asyncio.run(race())
    assert sum(isinstance(value, ExtensionRevisionConflictError) for value in results) == 1
    current = asyncio.run(store.get_connection(scope=scope, connection_id="mcp"))
    assert current.revision == 2
    with store.connect() as connection:
        rows = connection.execute("SELECT credential_ref FROM mcp_credential_versions").fetchall()
    assert rows == [{"credential_ref": current.credential_ref}]
    with pytest.raises(ExtensionRevisionConflictError):
        asyncio.run(
            service.revoke(verified=verified, connection_id="mcp", expected_connection_revision=1)
        )


def test_revoke_enabled_connection_and_no_automatic_reenable(dsn, protector):
    service, store, verified, scope = management(dsn, protector)
    current = asyncio.run(
        service.provision(
            verified=verified, connection_id="mcp", expected_connection_revision=1, token=TOKEN
        )
    )
    enabled = type(current).model_validate(current.model_dump() | {"enabled": True, "revision": 3})
    asyncio.run(
        PostgresExtensionStore(dsn, deployment_namespace="dev").save_mcp(
            scope=scope, connection=enabled, expected_revision=2
        )
    )
    revoked = asyncio.run(
        service.revoke(verified=verified, connection_id="mcp", expected_connection_revision=3)
    )
    assert not revoked.enabled
    fresh = asyncio.run(
        service.provision(
            verified=verified, connection_id="mcp", expected_connection_revision=4, token=TOKEN
        )
    )
    assert fresh.auth_state.value == "ready" and not fresh.enabled


def test_oauth_cannot_be_provisioned_as_arbitrary_token(protector):
    verified = _verified()
    scope = extension_scope_from_grant(verified, permission="extensions.manage")
    from agent_core.domain.extensions import McpConnection

    connection = McpConnection(
        scope=scope,
        connection_id="mcp",
        revision=1,
        endpoint="https://example.test/mcp",
        auth_mode="oauth",
        auth_state="pending",
    )
    store = AsyncMock(get_connection=AsyncMock(return_value=connection))
    with pytest.raises(ValueError, match="bearer or api_key"):
        asyncio.run(
            McpCredentialManagement(store, protector, "dev").provision(
                verified=verified, connection_id="mcp", expected_connection_revision=1, token=TOKEN
            )
        )
    store.publish.assert_not_called()

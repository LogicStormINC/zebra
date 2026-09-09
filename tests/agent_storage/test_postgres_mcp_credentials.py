"""Encrypted credential acceptance; migrations run only in disposable test schemas."""

import asyncio
import base64
from dataclasses import replace

import pytest
from agent_core.domain.extensions import ExtensionScope, McpConnection
from agent_core.domain.mcp_credentials import McpCredentialBinding, StoredMcpCredential
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_security.mcp_credential_protection import McpCredentialProtector
from agent_security.secret_store import InMemorySecretStore, SecretMaterial
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.mcp_credentials import PostgresMcpCredentialStore
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.types.json import Jsonb

from tests.agent_storage import test_postgres_extensions as extension_fixtures

SCOPE = extension_fixtures.SCOPE
dsn = extension_fixtures.dsn
postgres_dsn = extension_fixtures.postgres_dsn

TOKEN = "fixture-only-not-a-real-credential"


@pytest.fixture
def protector():
    key = base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()
    return McpCredentialProtector(
        InMemorySecretStore(
            {
                "key": SecretMaterial(handle="key", backend="fixture", version="1", value=key),
            }
        ),
        "key",
        "1",
    )


def record(protector, *, revision=1, scope=SCOPE, **updates):
    binding = McpCredentialBinding(
        deployment_namespace="dev",
        scope=scope,
        connection_id="mcp",
        endpoint="https://example.test/mcp",
        auth_mode="bearer",
        credential_ref="credential",
        credential_revision=revision,
    )
    binding = McpCredentialBinding.model_validate({**binding.model_dump(), **updates})
    return StoredMcpCredential(binding, protector.seal(binding, TOKEN))


def setup(dsn, *, scope=SCOPE):
    configs = PostgresExtensionStore(dsn, deployment_namespace="dev")
    asyncio.run(
        configs.save_mcp(
            scope=scope,
            connection=McpConnection(
                scope=scope,
                connection_id="mcp",
                revision=1,
                endpoint="https://example.test/mcp",
                auth_mode="bearer",
                auth_state="pending",
                enabled=False,
            ),
            expected_revision=None,
        )
    )
    return PostgresMcpCredentialStore(dsn, deployment_namespace="dev")


def test_restart_and_immutable_ciphertext_history(dsn, protector):
    store = setup(dsn)
    first = record(protector)
    asyncio.run(store.save(scope=SCOPE, record=first, expected_revision=None))
    second = record(protector, revision=2)
    asyncio.run(store.save(scope=SCOPE, record=second, expected_revision=1))
    restarted = PostgresMcpCredentialStore(dsn, deployment_namespace="dev")
    latest = asyncio.run(
        restarted.get(scope=SCOPE, connection_id="mcp", credential_ref="credential")
    )
    old = asyncio.run(
        restarted.get(scope=SCOPE, connection_id="mcp", credential_ref="credential", revision=1)
    )
    assert old == first and latest == second
    assert protector.unseal(latest.binding, latest.envelope).value == TOKEN
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM mcp_credential_versions ORDER BY revision"
        ).fetchall()
    assert len(rows) == 2
    assert TOKEN not in str(rows)
    assert all(TOKEN.encode() not in bytes(row["ciphertext"]) for row in rows)


@pytest.mark.parametrize(
    "field", ["authority_issuer", "namespace_id", "principal_id", "workspace_id"]
)
def test_cross_scope_read_and_write_rejected(dsn, protector, field):
    store = setup(dsn)
    original = record(protector)
    asyncio.run(store.save(scope=SCOPE, record=original, expected_revision=None))
    foreign = ExtensionScope.model_validate({**SCOPE.model_dump(), field: "other"})
    with pytest.raises(ExtensionNotFoundError):
        asyncio.run(store.get(scope=foreign, connection_id="mcp", credential_ref="credential"))
    with pytest.raises(ValueError, match="scope mismatch"):
        asyncio.run(store.save(scope=foreign, record=original, expected_revision=None))


def test_same_ids_two_users_and_deployments(dsn, protector):
    store = setup(dsn)
    foreign = ExtensionScope.model_validate({**SCOPE.model_dump(), "principal_id": "other"})
    setup(dsn, scope=foreign)
    for scope in (SCOPE, foreign):
        asyncio.run(
            store.save(scope=scope, record=record(protector, scope=scope), expected_revision=None)
        )
        result = asyncio.run(
            store.get(scope=scope, connection_id="mcp", credential_ref="credential")
        )
        assert result.binding.scope == scope
    other_deploy = PostgresMcpCredentialStore(dsn, deployment_namespace="other")
    with pytest.raises(ExtensionNotFoundError):
        asyncio.run(other_deploy.get(scope=SCOPE, connection_id="mcp", credential_ref="credential"))


def test_concurrent_compare_and_swap_has_one_winner(dsn, protector):
    store = setup(dsn)
    asyncio.run(store.save(scope=SCOPE, record=record(protector), expected_revision=None))

    async def race():
        return await asyncio.gather(
            *[
                store.save(scope=SCOPE, record=record(protector, revision=2), expected_revision=1)
                for _ in range(2)
            ],
            return_exceptions=True,
        )

    results = asyncio.run(race())
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ExtensionRevisionConflictError) for result in results) == 1
    with store.connect() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM mcp_credential_versions").fetchone()["n"]
            == 2
        )


@pytest.mark.parametrize(
    "updates", [{"endpoint": "https://other.test/mcp"}, {"auth_mode": "oauth"}]
)
def test_connection_binding_mismatch_rolls_back(dsn, protector, updates):
    store = setup(dsn)
    with pytest.raises(ExtensionRevisionConflictError):
        asyncio.run(
            store.save(scope=SCOPE, record=record(protector, **updates), expected_revision=None)
        )
    with store.connect() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM mcp_credential_versions").fetchone()["n"]
            == 0
        )


def test_missing_parent_rejected(dsn, protector):
    store = PostgresMcpCredentialStore(dsn, deployment_namespace="dev")
    with pytest.raises(ExtensionNotFoundError):
        asyncio.run(store.save(scope=SCOPE, record=record(protector), expected_revision=None))


def test_storage_payload_tamper_rejected(dsn, protector):
    store = setup(dsn)
    original = record(protector)
    asyncio.run(store.save(scope=SCOPE, record=original, expected_revision=None))
    with store.connect() as connection:
        connection.execute(
            "UPDATE mcp_credential_versions SET binding = %s",
            (Jsonb({**original.binding.model_dump(mode="json"), "credential_revision": 2}),),
        )
    with pytest.raises(ValueError, match="coordinates"):
        asyncio.run(store.get(scope=SCOPE, connection_id="mcp", credential_ref="credential"))


def test_invalid_revision_and_scope_rejected_without_io(protector, monkeypatch):
    store = PostgresMcpCredentialStore("unused", deployment_namespace="dev")
    monkeypatch.setattr(store, "connect", lambda: pytest.fail("unexpected database I/O"))
    with pytest.raises(ValueError):
        asyncio.run(
            store.save(scope=SCOPE, record=record(protector, revision=2), expected_revision=None)
        )
    with pytest.raises(ValueError):
        asyncio.run(store.save(scope=SCOPE, record=record(protector), expected_revision=True))
    with pytest.raises(ValueError):
        asyncio.run(
            store.get(scope=SCOPE, connection_id="mcp", credential_ref="credential", revision=0)
        )
    with pytest.raises(ValueError):
        asyncio.run(
            store.save(
                scope=SCOPE,
                record=replace(
                    record(protector),
                    binding=record(protector, deployment_namespace="other").binding,
                ),
                expected_revision=None,
            )
        )

"""Catalog versions survive restart and reject scope/configuration/payload drift."""

import asyncio

import pytest
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_core.ports.mcp_catalog import McpCatalogIntegrityError
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore

from tests.agent_storage import test_postgres_extensions as fixtures

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
SCOPE = fixtures.SCOPE


def setup(dsn):
    from agent_core.domain.extensions import McpConnection

    connection = McpConnection(
        scope=SCOPE, connection_id="mcp", revision=1, endpoint="https://example.test/mcp"
    )
    configs = PostgresExtensionStore(dsn, deployment_namespace="dev")
    asyncio.run(configs.save_mcp(scope=SCOPE, connection=connection, expected_revision=None))
    catalog = McpToolCatalog(
        connection=connection,
        protocol_version="2025-11-25",
        tools=(McpCatalogTool(name="search", input_schema_json='{"type":"object"}'),),
    )
    return configs, PostgresMcpCatalogStore(dsn, deployment_namespace="dev"), catalog


def read(store, catalog, **updates):
    return asyncio.run(
        store.get(
            **(
                {
                    "scope": SCOPE,
                    "connection_id": "mcp",
                    "config_revision": 1,
                    "expected_digest": catalog.digest,
                }
                | updates
            )
        )
    )


def test_restart_refresh_and_return_to_prior_catalog(dsn):
    _, store, first = setup(dsn)
    second = first.model_copy(update={"protocol_version": "2025-06-18"})
    for item in (first, second, first):
        asyncio.run(store.publish(scope=SCOPE, catalog=item))
        assert (
            asyncio.run(store.latest(scope=SCOPE, connection_id="mcp", config_revision=1)) == item
        )
    restarted = PostgresMcpCatalogStore(dsn, deployment_namespace="dev")
    assert read(restarted, first) == first and read(restarted, second) == second
    with store.connect() as transaction:
        assert (
            transaction.execute("SELECT count(*) AS n FROM mcp_catalog_versions").fetchone()["n"]
            == 2
        )


@pytest.mark.parametrize(
    "field", ["principal_id", "workspace_id", "authority_issuer", "namespace_id"]
)
def test_cross_scope_read_and_publish_rejected(dsn, field):
    _, store, catalog = setup(dsn)
    asyncio.run(store.publish(scope=SCOPE, catalog=catalog))
    foreign = SCOPE.model_copy(update={field: "foreign"})
    with pytest.raises(ExtensionNotFoundError):
        read(store, catalog, scope=foreign)
    with pytest.raises(ValueError, match="scope mismatch"):
        asyncio.run(store.publish(scope=foreign, catalog=catalog))
    with pytest.raises(ExtensionNotFoundError):
        read(PostgresMcpCatalogStore(dsn, deployment_namespace="other"), catalog)


def test_stale_refresh_does_not_erase_prior(dsn):
    configs, store, catalog = setup(dsn)
    asyncio.run(store.publish(scope=SCOPE, catalog=catalog))
    changed = catalog.connection.model_copy(update={"revision": 2, "enabled": False})
    asyncio.run(configs.save_mcp(scope=SCOPE, connection=changed, expected_revision=1))
    with pytest.raises(ExtensionRevisionConflictError):
        asyncio.run(store.publish(scope=SCOPE, catalog=catalog))
    assert read(store, catalog) == catalog
    with pytest.raises(ExtensionNotFoundError):
        asyncio.run(store.latest(scope=SCOPE, connection_id="mcp", config_revision=2))


def test_corruption_rejected_and_never_overwritten(dsn):
    _, store, catalog = setup(dsn)
    asyncio.run(store.publish(scope=SCOPE, catalog=catalog))
    with store.connect() as transaction:
        transaction.execute(
            "UPDATE mcp_catalog_versions SET payload=jsonb_set(payload, '{tools}', '[]')"
        )
    with pytest.raises(McpCatalogIntegrityError):
        read(store, catalog)
    with pytest.raises(McpCatalogIntegrityError):
        asyncio.run(store.publish(scope=SCOPE, catalog=catalog))

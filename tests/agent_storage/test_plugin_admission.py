"""Transaction locks retain current enabled package and ready component identities."""

import asyncio

import pytest
from agent_core.domain.extension_snapshots import ExtensionSnapshot, McpSnapshotEntry
from agent_core.domain.plugin_snapshots import PluginSnapshot
from agent_storage.postgres.extensions import (
    ExtensionSnapshotAdmissionConflictError,
    PostgresExtensionStore,
)
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
from agent_storage.postgres.plugin_admission import validate_plugin_snapshot_in_transaction
from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore

from tests.agent_storage.test_postgres_plugin_installations import (
    SCOPE,
    _catalog,
    _record,
    dsn,
    postgres_dsn,
)

__all__ = ["dsn", "postgres_dsn"]


def test_atomic_admission_rechecks_disable_and_never_accepts_changed_edges(dsn: str) -> None:
    async def seed():
        record = _record()
        catalog = _catalog(record.bindings[0].connection)
        record = record.model_copy(
            update={
                "bindings": (
                    record.bindings[0].model_copy(update={"catalog_digest": catalog.digest}),
                )
            }
        )
        store = PostgresPluginInstallationStore(dsn, deployment_namespace="cloud-a")
        await PostgresExtensionStore(dsn, deployment_namespace="cloud-a").save_mcp(
            scope=SCOPE, connection=catalog.connection, expected_revision=None
        )
        await PostgresMcpCatalogStore(dsn, deployment_namespace="cloud-a").publish(
            scope=SCOPE, catalog=catalog
        )
        await store.save(scope=SCOPE, installation=record, expected_revision=None)
        enabled = record.model_copy(update={"revision": 2, "enabled": True})
        await store.save(scope=SCOPE, installation=enabled, expected_revision=1)
        return store, enabled

    store, record = asyncio.run(seed())
    entry = McpSnapshotEntry(
        connection=record.bindings[0].connection, catalog_digest=record.bindings[0].catalog_digest
    )
    snapshot = ExtensionSnapshot(
        scope=SCOPE,
        session_id="session-a",
        turn_id="turn-a",
        mcp=(entry,),
        plugins=(PluginSnapshot.from_installation(record),),
    )
    with store.connect() as connection:
        validate_plugin_snapshot_in_transaction(connection, store, snapshot)
    asyncio.run(
        store.save(
            scope=SCOPE,
            installation=record.model_copy(update={"revision": 3, "enabled": False}),
            expected_revision=2,
        )
    )
    with store.connect() as connection, pytest.raises(ExtensionSnapshotAdmissionConflictError):
        validate_plugin_snapshot_in_transaction(connection, store, snapshot)

import asyncio
from unittest.mock import AsyncMock

import pytest
from agent_core.domain.extensions import McpConnection
from agent_core.domain.identifiers import SessionId
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_core.ports.extensions import ExtensionNotFoundError, McpConnectionPage
from agent_core.ports.mcp_catalog import McpCatalogIntegrityError, McpCatalogStore
from agent_security.extension_authority import extension_runtime_scope_from_grant
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
from zebra_agent_api.extension_mcp_selection import select_enabled_mcp
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission

from tests.agent_security.test_extension_authority import _verified
from tests.agent_storage import test_postgres_extensions as fixtures
from tests.api.test_extension_turn_admission import _admission

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn


def setup():
    admission, store, snapshots = _admission(0)
    scope = extension_runtime_scope_from_grant(_verified(scopes=["agent.run"]))
    connection = McpConnection(
        scope=scope,
        connection_id="mcp",
        revision=1,
        endpoint="https://example.test/mcp",
        enabled=True,
    )
    catalog = McpToolCatalog(
        connection=connection,
        protocol_version="2025-11-25",
        tools=(McpCatalogTool(name="events.search", input_schema_json='{"type":"object"}'),),
    )
    catalogs = AsyncMock(spec=McpCatalogStore)
    catalogs.latest.return_value = catalog
    store.list_mcp.return_value = McpConnectionPage(items=(connection,))
    return admission, store, snapshots, scope, catalog, catalogs


def test_turn_automatically_selects_enabled_tools_without_client_bindings():
    original, store, snapshots, scope, catalog, catalogs = setup()
    admission = CloudExtensionTurnAdmission(
        store, snapshots, original._task_authority, mcp_catalogs=catalogs
    )
    _, snapshot, _ = admission.prepare(
        verified=_verified(scopes=["agent.run"]),
        session_id=SessionId("session"),
        events=[],
        client_payload={"content": "search my events"},
    )
    assert snapshot.mcp[0].permissions.tools == ("events.search",)
    assert snapshot.mcp[0].catalog_digest == catalog.digest
    catalogs.latest.assert_awaited_once_with(scope=scope, connection_id="mcp", config_revision=1)
    store.list_skills.assert_not_awaited()
    catalogs.publish.assert_not_awaited()


def test_disabled_path_does_no_catalog_io():
    admission, store, _, _, _, catalogs = setup()
    _, snapshot, _ = admission.prepare(
        verified=_verified(scopes=["agent.run"]),
        session_id=SessionId("session"),
        events=[],
        client_payload={"content": "hello"},
    )
    assert snapshot.mcp == ()
    store.list_mcp.assert_not_awaited()
    catalogs.latest.assert_not_awaited()


@pytest.mark.parametrize(
    "change", [{"enabled": False}, {"auth_mode": "oauth", "auth_state": "pending"}]
)
def test_unavailable_connections_are_not_selected(change):
    _, store, _, scope, catalog, catalogs = setup()
    connection = McpConnection.model_validate(catalog.connection.model_dump() | change)
    store.list_mcp.return_value = McpConnectionPage(items=(connection,))
    assert asyncio.run(select_enabled_mcp(store, catalogs, scope)) == ()
    catalogs.latest.assert_not_awaited()


def test_unpublished_revision_does_not_block_conversation_or_use_old_catalog():
    _, store, _, scope, _, catalogs = setup()
    catalogs.latest.side_effect = ExtensionNotFoundError()
    assert asyncio.run(select_enabled_mcp(store, catalogs, scope)) == ()
    assert catalogs.latest.await_count == 1


def test_wrong_user_and_stale_catalog_are_rejected():
    _, store, _, scope, catalog, catalogs = setup()
    other = catalog.connection.model_copy(
        update={"scope": scope.model_copy(update={"principal_id": "other"})}
    )
    store.list_mcp.return_value = McpConnectionPage(items=(other,))
    with pytest.raises(McpCatalogIntegrityError):
        asyncio.run(select_enabled_mcp(store, catalogs, scope))
    catalogs.latest.assert_not_awaited()
    store.list_mcp.return_value = McpConnectionPage(items=(catalog.connection,))
    catalogs.latest.return_value = catalog.model_copy(update={"connection": other})
    with pytest.raises(McpCatalogIntegrityError):
        asyncio.run(select_enabled_mcp(store, catalogs, scope))


def test_paging_is_bounded_even_with_empty_pages():
    _, store, _, scope, _, catalogs = setup()
    store.list_mcp.return_value = McpConnectionPage(items=(), next_cursor="loop")
    with pytest.raises(ValueError, match="did not advance"):
        asyncio.run(select_enabled_mcp(store, catalogs, scope))
    assert store.list_mcp.await_count == 2


def test_duplicate_connections_and_tool_overflow_are_rejected():
    _, store, _, scope, catalog, catalogs = setup()
    store.list_mcp.return_value = McpConnectionPage(items=(catalog.connection, catalog.connection))
    with pytest.raises(McpCatalogIntegrityError):
        asyncio.run(select_enabled_mcp(store, catalogs, scope))
    store.list_mcp.return_value = McpConnectionPage(items=(catalog.connection,))
    catalogs.latest.return_value = McpToolCatalog(
        connection=catalog.connection,
        protocol_version=catalog.protocol_version,
        tools=tuple(
            McpCatalogTool(name=f"tool-{i}", input_schema_json='{"type":"object"}')
            for i in range(33)
        ),
    )
    with pytest.raises(ValueError, match="exceed"):
        asyncio.run(select_enabled_mcp(store, catalogs, scope))


def test_real_persisted_selection_and_disable(dsn):
    _, _, _, scope, catalog, _ = setup()
    store = PostgresExtensionStore(dsn, deployment_namespace="dev")
    catalogs = PostgresMcpCatalogStore(dsn, deployment_namespace="dev")
    asyncio.run(store.save_mcp(scope=scope, connection=catalog.connection, expected_revision=None))
    asyncio.run(catalogs.publish(scope=scope, catalog=catalog))
    selected = asyncio.run(select_enabled_mcp(store, catalogs, scope))
    assert selected[0].catalog_digest == catalog.digest
    assert selected[0].permissions.tools == ("events.search",)
    other = scope.model_copy(update={"principal_id": "other"})
    assert asyncio.run(select_enabled_mcp(store, catalogs, other)) == ()
    asyncio.run(
        store.save_mcp(
            scope=scope,
            connection=catalog.connection.model_copy(update={"enabled": False, "revision": 2}),
            expected_revision=1,
        )
    )
    assert asyncio.run(select_enabled_mcp(store, catalogs, scope)) == ()

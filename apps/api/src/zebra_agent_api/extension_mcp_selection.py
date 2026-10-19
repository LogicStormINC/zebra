"""Select current-user enabled catalogs without remote discovery or credentials."""

from agent_core.domain.extension_snapshots import ExtensionPermissions, McpSnapshotEntry
from agent_core.domain.extensions import ExtensionScope, McpConnection
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionPageRequest, ExtensionStore
from agent_core.ports.mcp_catalog import McpCatalogIntegrityError, McpCatalogStore


async def mcp_selection_entry(
    catalogs: McpCatalogStore,
    scope: ExtensionScope,
    connection: McpConnection,
) -> McpSnapshotEntry | None:
    if connection.scope != scope:
        raise McpCatalogIntegrityError("MCP selection returned invalid connection scope")
    if (
        not connection.enabled
        or connection.auth_mode.value not in ("none", "bearer")
        or connection.auth_state.value not in ("not_required", "ready")
    ):
        return None
    try:
        catalog = await catalogs.latest(
            scope=scope, connection_id=connection.connection_id, config_revision=connection.revision
        )
    except ExtensionNotFoundError:
        return None
    if catalog.connection != connection:
        raise McpCatalogIntegrityError("MCP selection catalog configuration mismatch")
    if not catalog.tools:
        return None
    return McpSnapshotEntry(
        connection=connection,
        catalog_digest=catalog.digest,
        permissions=ExtensionPermissions(tools=tuple(tool.name for tool in catalog.tools)),
    )


async def select_enabled_mcp(
    store: ExtensionStore,
    catalogs: McpCatalogStore,
    scope: ExtensionScope,
    selected_ids: tuple[str, ...] | None = None,
) -> tuple[McpSnapshotEntry, ...]:
    selected: list[McpSnapshotEntry] = []
    if selected_ids is not None:
        if len(selected_ids) > 32 or len(set(selected_ids)) != len(selected_ids):
            raise ValueError("selected MCP identities exceed bounded unique selection")
        for identifier in selected_ids:
            connection = await store.get_mcp(scope=scope, connection_id=identifier)
            if connection.connection_id != identifier:
                raise McpCatalogIntegrityError("MCP selection returned invalid connection identity")
            entry = await mcp_selection_entry(catalogs, scope, connection)
            if entry is None:
                raise ValueError("selected MCP connections are not ready")
            selected.append(entry)
    else:
        seen_ids: set[str] = set()
        cursors: set[str] = set()
        cursor: str | None = None
        for _ in range(4):
            page = await store.list_mcp(
                scope=scope, page=ExtensionPageRequest(limit=100, cursor=cursor)
            )
            for connection in page.items:
                if connection.connection_id in seen_ids:
                    raise McpCatalogIntegrityError(
                        "MCP selection returned duplicate connection identity"
                    )
                seen_ids.add(connection.connection_id)
                entry = await mcp_selection_entry(catalogs, scope, connection)
                if entry is not None:
                    selected.append(entry)
            if page.next_cursor is None:
                break
            if page.next_cursor in cursors:
                raise ValueError("MCP selection pagination did not advance")
            cursors.add(page.next_cursor)
            cursor = page.next_cursor
        else:
            raise ValueError("MCP selection exceeded its bounded scan")
    if len(selected) > 32 or sum(len(entry.permissions.tools) for entry in selected) > 32:
        raise ValueError("enabled MCP tools exceed the execution catalog limit")
    return tuple(sorted(selected, key=lambda item: item.connection.connection_id))

"""Select current-user enabled catalogs without remote discovery or credentials."""

from agent_core.domain.extension_snapshots import ExtensionPermissions, McpSnapshotEntry
from agent_core.domain.extensions import ExtensionScope
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionPageRequest, ExtensionStore
from agent_core.ports.mcp_catalog import McpCatalogIntegrityError, McpCatalogStore


async def select_enabled_mcp(
    store: ExtensionStore, catalogs: McpCatalogStore, scope: ExtensionScope
) -> tuple[McpSnapshotEntry, ...]:
    selected: list[McpSnapshotEntry] = []
    seen_ids: set[str] = set()
    cursors: set[str] = set()
    cursor: str | None = None
    tool_count = 0
    for _ in range(4):
        page = await store.list_mcp(
            scope=scope, page=ExtensionPageRequest(limit=100, cursor=cursor)
        )
        for connection in page.items:
            if connection.scope != scope or connection.connection_id in seen_ids:
                raise McpCatalogIntegrityError("MCP selection returned invalid connection identity")
            seen_ids.add(connection.connection_id)
            if not connection.enabled or connection.auth_mode.value not in ("none", "bearer"):
                continue
            if connection.auth_state.value not in ("not_required", "ready"):
                continue
            try:
                catalog = await catalogs.latest(
                    scope=scope,
                    connection_id=connection.connection_id,
                    config_revision=connection.revision,
                )
            except ExtensionNotFoundError:
                # A new/unrefreshed connection must not prevent ordinary conversation.
                continue
            if catalog.connection != connection:
                raise McpCatalogIntegrityError("MCP selection catalog configuration mismatch")
            if not catalog.tools:
                continue
            tool_count += len(catalog.tools)
            if tool_count > 32 or len(selected) >= 32:
                raise ValueError("enabled MCP tools exceed the execution catalog limit")
            selected.append(
                McpSnapshotEntry(
                    connection=connection,
                    catalog_digest=catalog.digest,
                    permissions=ExtensionPermissions(
                        tools=tuple(tool.name for tool in catalog.tools)
                    ),
                )
            )
        if page.next_cursor is None:
            return tuple(sorted(selected, key=lambda item: item.connection.connection_id))
        if page.next_cursor in cursors:
            raise ValueError("MCP selection pagination did not advance")
        cursors.add(page.next_cursor)
        cursor = page.next_cursor
    raise ValueError("MCP selection exceeded its bounded scan")

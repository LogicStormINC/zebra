"""Check stored catalog identity and eligibility without discovery or tool calls."""

from agent_core.domain.extension_snapshots import ExtensionPermissions, McpSnapshotEntry
from agent_core.domain.extensions import ExtensionScope, McpConnection
from agent_core.ports.extensions import ExtensionNotFoundError
from agent_core.ports.mcp_catalog import McpCatalogIntegrityError, McpCatalogStore


async def mcp_selection_entry(
    catalogs: McpCatalogStore,
    scope: ExtensionScope,
    connection: McpConnection,
    *, expected_digest: str | None = None,
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
        catalog = (
            await catalogs.get(
                scope=scope, connection_id=connection.connection_id,
                config_revision=connection.revision, expected_digest=expected_digest,
            ) if expected_digest is not None else await catalogs.latest(
                scope=scope, connection_id=connection.connection_id,
                config_revision=connection.revision,
            )
        )
    except ExtensionNotFoundError:
        return None
    if (catalog.connection != connection
            or expected_digest is not None and catalog.digest != expected_digest):
        raise McpCatalogIntegrityError("MCP selection catalog configuration mismatch")
    if not catalog.tools:
        return None
    return McpSnapshotEntry(
        connection=connection,
        catalog_digest=catalog.digest,
        permissions=ExtensionPermissions(tools=tuple(tool.name for tool in catalog.tools)),
    )


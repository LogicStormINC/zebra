"""Immutable catalog persistence, separate from discovery and use authorization."""

from typing import Protocol

from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.mcp_catalog import McpToolCatalog


class McpCatalogIntegrityError(ValueError):
    """Stored metadata does not match its pinned coordinates or digest."""


class McpCatalogStore(Protocol):
    async def publish(self, *, scope: ExtensionScope, catalog: McpToolCatalog) -> None: ...

    async def get(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
        config_revision: int,
        expected_digest: str,
    ) -> McpToolCatalog: ...

    async def latest(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
        config_revision: int,
    ) -> McpToolCatalog: ...

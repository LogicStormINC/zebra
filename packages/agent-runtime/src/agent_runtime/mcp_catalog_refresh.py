"""Management discovery orchestration; never authorizes tools/call or Agent execution."""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from agent_core.domain.extensions import ExtensionRevision, ExtensionScope, OpaqueExtensionId
from agent_core.domain.mcp_catalog import McpToolCatalog
from agent_core.domain.mcp_credentials import McpCredentialBinding
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_core.ports.mcp_catalog import McpCatalogIntegrityError, McpCatalogStore
from agent_core.ports.mcp_credentials import McpCredentialManagementStore, McpCredentialUseStore
from agent_security.extension_authority import extension_scope_from_grant
from agent_security.host_grant import HostGrantBindingError, VerifiedHostGrant
from agent_security.mcp_credential_protection import McpCredentialProtector
from agent_security.mcp_credential_release import _require_live_grant
from pydantic import TypeAdapter

from agent_runtime.mcp_catalog_discovery import discover_mcp_tool_catalog
from agent_runtime.mcp_http_authorization import McpHttpBearerCredential


class RefreshCredentialStore(McpCredentialManagementStore, McpCredentialUseStore, Protocol):
    """Same current configuration and credential authority used by management."""


@dataclass(frozen=True)
class McpCatalogRefresh:
    connections: RefreshCredentialStore = field(repr=False)
    catalogs: McpCatalogStore = field(repr=False)
    protector: McpCredentialProtector = field(repr=False)
    deployment_namespace: str

    async def read(
        self, *, verified: VerifiedHostGrant, connection_id: str
    ) -> McpToolCatalog:
        """Inspect current-revision metadata only; never discover or release secrets."""
        _require_live_grant(verified)
        scope = extension_scope_from_grant(verified, permission="extensions.read")
        TypeAdapter(OpaqueExtensionId).validate_python(connection_id)
        current = await self.connections.get_connection(scope=scope, connection_id=connection_id)
        if current.scope != scope or current.connection_id != connection_id:
            raise ExtensionNotFoundError("MCP connection unavailable")
        catalog = await self.catalogs.latest(
            scope=scope, connection_id=connection_id, config_revision=current.revision
        )
        if catalog.connection != current:
            raise McpCatalogIntegrityError("MCP catalog configuration mismatch")
        latest = await self.connections.get_connection(scope=scope, connection_id=connection_id)
        if latest != current:
            raise ExtensionRevisionConflictError("MCP connection changed during read")
        _require_live_grant(verified)
        return catalog

    async def refresh(
        self, *, verified: VerifiedHostGrant, connection_id: str, expected_revision: int
    ) -> McpToolCatalog:
        _require_live_grant(verified)
        scope = extension_scope_from_grant(verified, permission="extensions.manage")
        return await self.refresh_authorized(
            scope=scope, connection_id=connection_id, expected_revision=expected_revision,
            revalidate=lambda: _require_live_grant(verified),
        )

    async def refresh_authorized(
        self, *, scope: ExtensionScope, connection_id: str, expected_revision: int,
        revalidate: Callable[[], None],
    ) -> McpToolCatalog:
        """Internal composition only: caller supplies exact scope and live management checks."""
        revalidate()
        TypeAdapter(OpaqueExtensionId).validate_python(connection_id)
        TypeAdapter(ExtensionRevision).validate_python(expected_revision)
        current = await self.connections.get_connection(scope=scope, connection_id=connection_id)
        if current.scope != scope or current.connection_id != connection_id:
            raise ExtensionNotFoundError("MCP connection unavailable")
        if current.revision != expected_revision:
            raise ExtensionRevisionConflictError("MCP connection revision conflict")

        async def check() -> None:
            revalidate()
            latest = await self.connections.get_connection(scope=scope, connection_id=connection_id)
            if latest != current:
                raise ExtensionRevisionConflictError("MCP connection changed during discovery")
            revalidate()

        def authorize(endpoint: str, frame: Mapping[str, object]) -> None:
            if endpoint != current.endpoint or frame.get("method") not in (
                "initialize",
                "notifications/initialized",
                "tools/list",
            ):
                raise HostGrantBindingError("MCP refresh frame is not permitted")
            asyncio.run(check())

        async def release() -> McpHttpBearerCredential:
            assert current.credential_ref is not None
            record = await self.connections.get_for_use(scope=scope, expected_connection=current)
            expected = McpCredentialBinding(
                deployment_namespace=self.deployment_namespace,
                scope=scope,
                connection_id=connection_id,
                endpoint=current.endpoint,
                auth_mode="bearer",
                credential_ref=current.credential_ref,
                credential_revision=1,
            )
            if record.binding != expected:
                raise HostGrantBindingError("MCP credential binding mismatch")
            revalidate()
            return McpHttpBearerCredential(
                current.endpoint, self.protector.unseal(expected, record.envelope)
            )

        def resolve(endpoint: str, frame: Mapping[str, object]) -> McpHttpBearerCredential:
            authorize(endpoint, frame)
            return asyncio.run(release())

        bearer = current.auth_mode.value == "bearer"
        catalog = await asyncio.to_thread(
            discover_mcp_tool_catalog,
            current,
            credential_resolver=resolve if bearer else None,
            frame_authorizer=None if bearer else authorize,
        )
        if catalog.connection != current:
            raise HostGrantBindingError("MCP discovered catalog binding mismatch")
        await check()
        await self.catalogs.publish(scope=scope, catalog=catalog)
        revalidate()
        return catalog

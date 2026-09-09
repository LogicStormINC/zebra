"""Management-only Broker service; no runtime token release or OAuth exchange."""

from dataclasses import dataclass, field
from uuid import uuid4

from agent_core.domain.extensions import McpConnection
from agent_core.domain.mcp_credentials import McpCredentialBinding, StoredMcpCredential
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_core.ports.mcp_credentials import McpCredentialManagementStore

from agent_security.extension_authority import extension_scope_from_grant
from agent_security.host_grant import VerifiedHostGrant
from agent_security.mcp_credential_protection import McpCredentialProtector


@dataclass(frozen=True)
class McpCredentialManagement:
    store: McpCredentialManagementStore = field(repr=False)
    protector: McpCredentialProtector = field(repr=False)
    deployment_namespace: str

    async def provision(
        self,
        *,
        verified: VerifiedHostGrant,
        connection_id: str,
        expected_connection_revision: int,
        token: str,
    ) -> McpConnection:
        scope = extension_scope_from_grant(verified, permission="extensions.manage")
        current = await self.store.get_connection(scope=scope, connection_id=connection_id)
        if current.scope != scope or current.connection_id != connection_id:
            raise ExtensionNotFoundError("MCP connection unavailable")
        if type(expected_connection_revision) is not int or expected_connection_revision < 1:
            raise ValueError("invalid expected connection revision")
        if current.revision != expected_connection_revision:
            raise ExtensionRevisionConflictError("MCP connection revision conflict")
        mode = current.auth_mode.value
        if mode != "bearer" and mode != "api_key":
            raise ValueError("direct token provisioning requires bearer or api_key mode")
        binding = McpCredentialBinding(
            deployment_namespace=self.deployment_namespace,
            scope=scope,
            connection_id=connection_id,
            endpoint=current.endpoint,
            auth_mode="bearer" if mode == "bearer" else "api_key",
            credential_ref=f"credential_{uuid4().hex}",
            credential_revision=1,
        )
        record = StoredMcpCredential(binding, self.protector.seal(binding, token))
        return await self.store.publish(
            scope=scope,
            record=record,
            expected_connection_revision=expected_connection_revision,
        )

    async def revoke(
        self,
        *,
        verified: VerifiedHostGrant,
        connection_id: str,
        expected_connection_revision: int,
    ) -> McpConnection:
        scope = extension_scope_from_grant(verified, permission="extensions.manage")
        return await self.store.revoke(
            scope=scope,
            connection_id=connection_id,
            expected_connection_revision=expected_connection_revision,
        )

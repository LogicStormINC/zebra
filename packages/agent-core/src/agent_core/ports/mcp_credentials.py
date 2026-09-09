"""Broker-internal encrypted storage. Reading ciphertext does not grant token use."""

from typing import Protocol

from agent_core.domain.extensions import ExtensionScope, McpConnection
from agent_core.domain.mcp_credentials import StoredMcpCredential


class McpCredentialStore(Protocol):
    async def save(
        self,
        *,
        scope: ExtensionScope,
        record: StoredMcpCredential,
        expected_revision: int | None,
    ) -> None:
        """Create revision 1 or append expected+1; conflict never overwrites history."""
        ...

    async def get(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
        credential_ref: str,
        revision: int | None = None,
    ) -> StoredMcpCredential:
        """Return exact or latest encrypted version in the independently supplied scope."""
        ...


class McpCredentialManagementStore(Protocol):
    async def get_connection(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
    ) -> McpConnection: ...

    async def publish(
        self,
        *,
        scope: ExtensionScope,
        record: StoredMcpCredential,
        expected_connection_revision: int,
    ) -> McpConnection:
        """Create a fresh credential ref and publish ready state atomically, preserving enabled."""
        ...

    async def revoke(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
        expected_connection_revision: int,
    ) -> McpConnection:
        """Atomically disable and revoke configuration; preserve encrypted history."""
        ...


class McpCredentialUseStore(Protocol):
    async def get_for_use(
        self, *, scope: ExtensionScope, expected_connection: McpConnection
    ) -> StoredMcpCredential:
        """Read published ciphertext under a current-configuration lock, not execution authority."""
        ...

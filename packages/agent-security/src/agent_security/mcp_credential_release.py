"""Internal Broker release, never a public decrypt endpoint or a model tool."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from agent_core.domain.extensions import McpConnection
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.mcp_credentials import McpCredentialBinding
from agent_core.ports.extension_snapshots import ExtensionSnapshotStore, ExtensionTaskAuthorityStore
from agent_core.ports.mcp_credentials import McpCredentialUseStore

from agent_security.extension_authority import extension_runtime_scope_from_task_grant
from agent_security.host_grant import HostGrantBindingError, VerifiedHostGrant
from agent_security.mcp_credential_protection import McpCredentialProtector
from agent_security.mcp_execution_authority import McpWorkerAuthority
from agent_security.secret_store import SecretMaterial


@dataclass(frozen=True)
class McpCredentialRelease:
    store: McpCredentialUseStore = field(repr=False)
    snapshots: ExtensionSnapshotStore = field(repr=False)
    tasks: ExtensionTaskAuthorityStore = field(repr=False)
    protector: McpCredentialProtector = field(repr=False)
    deployment_namespace: str

    async def authorize_snapshot(
        self,
        *,
        verified: VerifiedHostGrant | McpWorkerAuthority,
        session_id: str,
        turn_id: str,
        expected_digest: str,
        connection_id: str,
        endpoint: str,
        kind: Literal["tools", "resources", "prompts"],
        name: str,
    ) -> McpConnection:
        """Coordinates/digest must come from a verified server execution binding.

        Caller must also enforce live lease, operation policy and network policy.
        This returns frozen configuration only; caller must check current config
        before use. No credential is read or decrypted by snapshot authorization.
        """
        require_live_mcp_authority(verified)
        ceiling = await asyncio.to_thread(self.tasks.resolve_task_ceiling, session_id=session_id)
        scope = (
            verified.scope(session_id=session_id, ceiling=ceiling)
            if isinstance(verified, McpWorkerAuthority)
            else extension_runtime_scope_from_task_grant(verified, ceiling.binding)
        )
        if "agent.execute" not in ceiling.binding.effective_capabilities:
            raise HostGrantBindingError("Task does not permit Agent execution")
        snapshot = await self.snapshots.get(
            scope=scope, session_id=session_id, turn_id=turn_id, expected_digest=expected_digest
        )
        if (snapshot.scope, snapshot.session_id, snapshot.turn_id, snapshot.digest) != (
            scope,
            session_id,
            turn_id,
            expected_digest,
        ):
            raise HostGrantBindingError("MCP execution snapshot binding mismatch")
        entry = next(
            (item for item in snapshot.mcp if item.connection.connection_id == connection_id), None
        )
        if (
            kind not in ("tools", "resources", "prompts")
            or entry is None
            or name not in getattr(entry.permissions, kind)
        ):
            raise HostGrantBindingError("MCP operation is outside the frozen permission ceiling")
        current = entry.connection
        if current.endpoint != endpoint:
            raise HostGrantBindingError("MCP credential target endpoint mismatch")
        require_live_mcp_authority(verified)
        return current

    async def release(
        self,
        *,
        verified: VerifiedHostGrant | McpWorkerAuthority,
        session_id: str,
        turn_id: str,
        expected_digest: str,
        connection_id: str,
        endpoint: str,
        kind: Literal["tools", "resources", "prompts"],
        name: str,
    ) -> SecretMaterial:
        current = await self.authorize_snapshot(
            verified=verified,
            session_id=session_id,
            turn_id=turn_id,
            expected_digest=expected_digest,
            connection_id=connection_id,
            endpoint=endpoint,
            kind=kind,
            name=name,
        )
        scope = current.scope
        mode = current.auth_mode.value
        if mode not in ("bearer", "api_key") or current.credential_ref is None:
            raise HostGrantBindingError("MCP authentication mode is not available for release")
        expected = McpCredentialBinding(
            deployment_namespace=self.deployment_namespace,
            scope=scope,
            connection_id=connection_id,
            endpoint=current.endpoint,
            auth_mode="bearer" if mode == "bearer" else "api_key",
            credential_ref=current.credential_ref,
            credential_revision=1,
        )
        record = await self.store.get_for_use(scope=scope, expected_connection=current)
        if record.binding != expected:
            raise HostGrantBindingError("MCP credential binding mismatch")
        require_live_mcp_authority(verified)
        return self.protector.unseal(expected, record.envelope)


def require_live_mcp_authority(verified: VerifiedHostGrant | McpWorkerAuthority) -> None:
    if isinstance(verified, McpWorkerAuthority):
        verified.require_live()
    else:
        _require_live_grant(verified)


def _require_live_grant(verified: VerifiedHostGrant) -> None:
    if (
        not isinstance(verified, VerifiedHostGrant)
        or not isinstance(verified.context, HostContextEnvelope)
        or verified.context.expires_at is None
        or verified.context.expires_at <= datetime.now(UTC)
    ):
        raise HostGrantBindingError("MCP credential release requires an unexpired verified grant")

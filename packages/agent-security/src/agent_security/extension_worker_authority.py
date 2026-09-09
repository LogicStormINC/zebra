"""Explicit configuration authority on top of ordinary Worker execution evidence."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence, LeaseLostError
from agent_core.ports.extension_snapshots import ExtensionTaskAuthorityStore
from agent_core.ports.lease_store import LeaseStorePort

from agent_security.host_grant import HostGrantBindingError
from agent_security.mcp_execution_authority import McpWorkerAuthority


@dataclass(frozen=True)
class ExtensionWorkerAuthority:
    session_id: SessionId
    expected_scope: ExtensionScope
    fence: LeaseFence
    tasks: ExtensionTaskAuthorityStore
    leases: LeaseStorePort
    fresh_authority: Callable[[], McpWorkerAuthority]

    def __call__(
        self, permission: Literal["extensions.read", "extensions.manage"],
    ) -> ExtensionScope:
        if permission not in ("extensions.read", "extensions.manage"):
            raise HostGrantBindingError("Unsupported extension permission")
        lease = self.leases.get(self.session_id)
        if (lease is None or lease.session_id != self.session_id or lease.fence != self.fence
                or lease.expires_at <= datetime.now(UTC)):
            raise LeaseLostError("Extension management requires the current Worker lease")
        ceiling = self.tasks.resolve_task_ceiling(session_id=str(self.session_id))
        scope = self.fresh_authority().scope(session_id=str(self.session_id), ceiling=ceiling)
        context = ceiling.binding.host_capability.host_context
        if scope != self.expected_scope or context is None:
            raise HostGrantBindingError("Extension management identity changed")
        context.require_scope(permission)
        return scope

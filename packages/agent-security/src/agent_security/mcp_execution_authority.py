"""Internal Worker evidence for MCP; never an HTTP request credential."""

from dataclasses import dataclass
from datetime import UTC, datetime

from agent_core.domain.execution_authority import (
    ExecutionAuthorityDecision,
    ExecutionAuthoritySnapshot,
)
from agent_core.domain.extension_snapshots import ExtensionTaskCeiling
from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.task_bindings import host_context_digest

from agent_security.host_grant import HostGrantBindingError


@dataclass(frozen=True)
class McpWorkerAuthority:
    """Server composition supplies evidence from existing attempt revalidation."""

    session_id: str
    snapshot: ExecutionAuthoritySnapshot

    def require_live(self) -> None:
        now = datetime.now(UTC)
        snapshot = ExecutionAuthoritySnapshot.model_validate(self.snapshot.model_dump())
        if (
            snapshot.expires_at <= now
            or snapshot.issued_at > now
            or snapshot.validated_at > now
            or snapshot.resolution not in (
                ExecutionAuthorityDecision.ALLOWED,
                ExecutionAuthorityDecision.NARROWED,
            )
            or "agent.execute" not in snapshot.granted_authorities
        ):
            raise HostGrantBindingError("MCP Worker execution authority is not live")

    def scope(self, *, session_id: str, ceiling: ExtensionTaskCeiling) -> ExtensionScope:
        self.require_live()
        binding = ceiling.binding
        host = binding.host_capability
        snapshot = self.snapshot
        if (
            self.session_id != session_id
            or snapshot.authority_issuer != host.authority_issuer
            or snapshot.namespace_id != host.namespace_id
            or snapshot.source_authority_digest != binding.binding_digest[:64]
            or snapshot.policy_effective_digest != binding.zebra_policy_digest
            or snapshot.agent_definition_snapshot_digest
            != binding.agent_capability_ceiling.definition_snapshot_digest
            or "agent.execute" not in binding.effective_capabilities
            or host.grant_expires_at is None
            or host.grant_expires_at <= datetime.now(UTC)
            or snapshot.expires_at > host.grant_expires_at
        ):
            raise HostGrantBindingError("MCP Worker authority differs from current Task binding")
        return extension_scope_from_task_ceiling(ceiling)


def extension_scope_from_task_ceiling(ceiling: ExtensionTaskCeiling) -> ExtensionScope:
    """Shared recovery/release identity, including the exact frozen principal."""
    binding = ceiling.binding
    host = binding.host_capability
    context = host.host_context
    if context is None:
        raise ValueError("extension Worker requires a frozen Host context")
    if host_context_digest(context) != host.grant_digest:
        raise ValueError("extension Task Host context digest is corrupt")
    if (
        host.host_app_id != context.host_app_id
        or host.namespace_id != context.namespace_id
        or binding.task_id != ceiling.task_id
    ):
        raise ValueError("extension Task authority coordinates disagree")
    principals = tuple(
        resource.resource_id
        for resource in context.resource_refs
        if resource.resource_type == "principal"
    )
    if len(principals) != 1:
        raise ValueError("extension Worker requires exactly one frozen principal")
    return ExtensionScope(
        authority_issuer=host.authority_issuer,
        namespace_id=host.namespace_id,
        principal_id=principals[0],
        workspace_id=context.workspace_ref,
    )

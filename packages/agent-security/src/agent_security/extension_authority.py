"""Bind extension configuration access to an explicitly authorized Host Grant."""

from typing import Literal

from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.task_bindings import TaskBindingSnapshot

from agent_security.host_grant import HostGrantBindingError, VerifiedHostGrant


def extension_scope_from_grant(
    verified: VerifiedHostGrant,
    *,
    permission: Literal["extensions.read", "extensions.manage"],
) -> ExtensionScope:
    if permission not in ("extensions.read", "extensions.manage"):
        raise HostGrantBindingError("Extension permission is not supported")
    if not isinstance(verified, VerifiedHostGrant) or not isinstance(
        verified.context, HostContextEnvelope
    ):
        raise HostGrantBindingError("Extension access requires a verified Host Grant")
    try:
        verified.context.require_scope(permission)
        return ExtensionScope(
            authority_issuer=verified.authority_issuer,
            namespace_id=verified.context.namespace_id,
            principal_id=verified.subject_ref,
            workspace_id=verified.context.workspace_ref,
        )
    except ValueError:
        raise HostGrantBindingError("Extension authority or permission is invalid") from None


def extension_runtime_scope_from_grant(verified: VerifiedHostGrant) -> ExtensionScope:
    """Bind runtime admission to the normal Agent execution authority.

    Listing and management permissions intentionally remain separate: an
    already-enabled extension can run without exposing its configuration APIs.
    """
    if not isinstance(verified, VerifiedHostGrant) or not isinstance(
        verified.context, HostContextEnvelope
    ):
        raise HostGrantBindingError("Extension runtime requires a verified Host Grant")
    try:
        verified.context.require_scope("agent.run")
        return ExtensionScope(
            authority_issuer=verified.authority_issuer,
            namespace_id=verified.context.namespace_id,
            principal_id=verified.subject_ref,
            workspace_id=verified.context.workspace_ref,
        )
    except ValueError:
        raise HostGrantBindingError("Extension runtime authority is invalid") from None


def extension_runtime_scope_from_task_grant(
    verified: VerifiedHostGrant,
    binding: TaskBindingSnapshot,
) -> ExtensionScope:
    """Require the current Grant to be the same principal-bound Task authority."""

    scope = extension_runtime_scope_from_grant(verified)
    if not isinstance(binding, TaskBindingSnapshot):
        raise HostGrantBindingError("Extension runtime requires a Task binding")
    current = verified.context
    bound = binding.host_capability.host_context
    current_principal = _single_principal(current)
    bound_principal = _single_principal(bound)
    host = binding.host_capability
    if (
        current_principal != verified.subject_ref
        or bound_principal != current_principal
        or host.authority_issuer != verified.authority_issuer
        or host.host_app_id != current.host_app_id
        or host.namespace_id != current.namespace_id
        or bound is None
        or (
            bound.host_app_id,
            bound.origin,
            bound.namespace_id,
            bound.workspace_ref,
        )
        != (
            current.host_app_id,
            current.origin,
            current.namespace_id,
            current.workspace_ref,
        )
    ):
        raise HostGrantBindingError("Extension runtime Task authority drifted")
    return scope


def _single_principal(context: HostContextEnvelope | None) -> str | None:
    if context is None:
        return None
    principals = tuple(
        resource.resource_id
        for resource in context.resource_refs
        if resource.resource_type == "principal"
    )
    if len(principals) != 1:
        raise HostGrantBindingError("Extension runtime requires exactly one principal")
    return principals[0]

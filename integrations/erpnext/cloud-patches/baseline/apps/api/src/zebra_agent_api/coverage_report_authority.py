"""Read-only current authority checks for a historically certified report."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.host_connectors import HostConnectorProfileVersion, HostConnectorStatus
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_integrations.coverage_snapshot_invocation import HISTORY_RESOURCE_TYPE
from agent_security.host_grant import VerifiedHostGrant
from agent_storage.postgres.host_auth import PostgresHostAuthorityStore
from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi


def _resource(context: HostContextEnvelope, kind: str) -> str:
    refs = [ref.resource_id for ref in context.resource_refs if ref.resource_type == kind]
    if len(refs) != 1:
        raise PermissionError("report authority requires one exact resource")
    return refs[0]


def validate_report_grant(
    binding: TaskBindingSnapshot,
    grant: VerifiedHostGrant,
    *,
    history_ref: str,
) -> None:
    """A fresh read grant replaces neither the Task's owner nor its resource."""
    if type(grant) is not VerifiedHostGrant:
        raise PermissionError("verified report authority required")
    fresh = grant.context
    host = binding.host_capability
    bound = host.host_context
    if (
        bound is None
        or fresh.expires_at is None
        or datetime.now(UTC) >= fresh.expires_at
        or grant.grant_id != fresh.grant_id
        or not {"history.read", "artifact.read"} <= set(fresh.scopes)
        or grant.authority_issuer != host.authority_issuer
        or fresh.host_app_id != host.host_app_id
        or fresh.namespace_id != host.namespace_id
        or fresh.host_app_id != bound.host_app_id
        or fresh.namespace_id != bound.namespace_id
        or fresh.origin != bound.origin
        or fresh.workspace_ref != bound.workspace_ref
        or _resource(fresh, "principal") != _resource(bound, "principal")
        or _resource(fresh, HISTORY_RESOURCE_TYPE) != history_ref
        or _resource(bound, HISTORY_RESOURCE_TYPE) != history_ref
    ):
        raise PermissionError("report authority does not match the frozen Task")


def current_report_profile(
    api: ZebraAgentApi,
    task_id: TaskId,
    binding: TaskBindingSnapshot,
    grant: VerifiedHostGrant,
    *,
    history_ref: str,
    dsn: str,
    deployment: str,
) -> HostConnectorProfileVersion:
    """No grant consumption, renewal, manifest discovery or registry mutation."""
    validate_report_grant(binding, grant, history_ref=history_ref)
    control = api.cloud_control
    if (
        control is None
        or control.deployment_namespace != deployment
        or control._database._dsn != dsn
    ):
        raise RuntimeError("co-located Task authority reader unavailable")
    current = control.load_task_binding(task_id)
    if current != binding or binding.task_id != str(task_id):
        raise PermissionError("report Task binding changed or disappeared")
    fresh = grant.context
    registry = PostgresHostAuthorityStore(dsn, deployment_namespace=deployment).get_registry(
        host_app_id=fresh.host_app_id,
        namespace_id=fresh.namespace_id,
    )
    if (
        registry is None
        or not registry.active
        or registry.issuer != grant.authority_issuer
        or fresh.origin not in registry.allowed_origins
        or grant.algorithm.value not in registry.algorithms
        or fresh.policy_version != registry.policy_version
    ):
        raise PermissionError("current report Host authority is revoked")
    connectors = PostgresHostConnectorRegistry(dsn, deployment_namespace=deployment)
    pinned = connectors.resolve_binding(fresh.host_app_id, fresh.namespace_id)
    host = binding.host_capability
    if (
        pinned is None
        or not pinned.active
        or pinned.connector_id != host.connector_id
        or pinned.profile_revision != host.connector_profile_revision
    ):
        raise PermissionError("report connector binding changed or disappeared")
    profile = connectors.get_profile(
        host.host_app_id,
        host.connector_id,
        host.connector_profile_revision,
    )
    if (
        profile is None
        or profile.status is HostConnectorStatus.REVOKED
        or profile.profile_digest != host.connector_profile_digest
    ):
        raise PermissionError("report connector profile changed or revoked")
    return profile

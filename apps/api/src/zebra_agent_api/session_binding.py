
"""Freeze the Task binding at cloud admission (Phase F3).

The cloud create path derives an `AgentCapabilityCeilingSnapshot` from the
published Definition (when bound) and a `HostCapabilitySnapshot` from the
verified HostContextEnvelope, then persists the immutable
`TaskBindingSnapshot` so the Worker's binding-aware authority (F1) and
pinned egress (F2) consume frozen facts. Digests are computed from the
envelope content — no secret material ever enters the snapshot.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
)
from agent_storage.postgres.task_admission import save_task_binding

from zebra_agent_api.responses import ApiResponse

DEFAULT_CAPABILITIES = capability_set(["agent.execute"])
NO_CONNECTOR_DIGEST = "0" * 64


def envelope_grant_digest(envelope: HostContextEnvelope) -> str:
    canonical = {
        "hostAppId": envelope.host_app_id,
        "namespaceId": envelope.namespace_id,
        "scopes": sorted(envelope.scopes),
        "resources": [
            {"type": ref.resource_type, "id": ref.resource_id}
            for ref in envelope.resource_refs
        ],
        "policyVersion": envelope.policy_version,
        "origin": envelope.origin,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def freeze_task_binding(
    session_id: object,
    *,
    host_context: HostContextEnvelope,
    definition_snapshot_digest: str | None,
    deployment_namespace: str,
    dsn: str,
) -> str | None:
    """Derive and persist the binding; returns the digest or None on refusal.

    Refusal (never a crash) keeps today's behavior when persistence is
    unavailable — the Worker falls back to the deployment resolver.
    """

    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest=definition_snapshot_digest or NO_CONNECTOR_DIGEST,
        capability_profile_ref="profile/default@1",
        capabilities=DEFAULT_CAPABILITIES,
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id=host_context.host_app_id,
        authority_issuer=host_context.origin,
        namespace_id=host_context.namespace_id,
        grant_digest=envelope_grant_digest(host_context),
        grant_expires_at=host_context.expires_at,
        connector_id=f"{host_context.host_app_id}-unbound",
        connector_profile_revision=1,
        connector_profile_digest=NO_CONNECTOR_DIGEST,
        manifest_digest=NO_CONNECTOR_DIGEST,
        capabilities=DEFAULT_CAPABILITIES,
        resource_binding_digest=NO_CONNECTOR_DIGEST,
        bound_at=datetime.now(UTC),
    )
    binding = TaskBindingSnapshot(
        task_id=str(session_id),
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest=NO_CONNECTOR_DIGEST,
        effective_capabilities=DEFAULT_CAPABILITIES,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )
    try:
        return save_task_binding(
            dsn,
            deployment_namespace=deployment_namespace,
            binding=binding,
        )
    except Exception:
        return None

def freeze_binding_for_response(
    response: object,
    host_context: HostContextEnvelope,
    definition_snapshot: object,
    *,
    deployment: str,
    storage_authority: str,
    database_url: str,
    stores: object,
) -> None:
    """Phase F3 entry from the API: freeze the binding after a 201.

    Cloud + PostgreSQL only; refusal keeps today's behavior silently.
    """



    assert isinstance(response, ApiResponse)
    if deployment != "cloud" or storage_authority != "postgresql":
        return
    digest = getattr(definition_snapshot, "definition_digest", None)
    freeze_task_binding(
        response.body.get("session_id"),
        host_context=host_context,
        definition_snapshot_digest=str(digest) if digest else None,
        deployment_namespace=str(getattr(stores, "deployment_namespace", "zebra")),
        dsn=database_url,
    )

def _build_binding_snapshot(
    session_id: object,
    *,
    host_context: HostContextEnvelope,
    definition_snapshot_digest: str | None,
) -> TaskBindingSnapshot:
    """Build the binding model without persisting (used by atomic admission)."""

    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest=definition_snapshot_digest or NO_CONNECTOR_DIGEST,
        capability_profile_ref="profile/default@1",
        capabilities=DEFAULT_CAPABILITIES,
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id=host_context.host_app_id,
        authority_issuer=host_context.origin,
        namespace_id=host_context.namespace_id,
        grant_digest=envelope_grant_digest(host_context),
        grant_expires_at=host_context.expires_at,
        connector_id=f"{host_context.host_app_id}-unbound",
        connector_profile_revision=1,
        connector_profile_digest=NO_CONNECTOR_DIGEST,
        manifest_digest=NO_CONNECTOR_DIGEST,
        capabilities=DEFAULT_CAPABILITIES,
        resource_binding_digest=NO_CONNECTOR_DIGEST,
        bound_at=datetime.now(UTC),
    )
    return TaskBindingSnapshot(
        task_id=str(session_id),
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest=NO_CONNECTOR_DIGEST,
        effective_capabilities=DEFAULT_CAPABILITIES,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )

def _admission_kwargs(
    settings: object, stores: object, idempotency_key: str | None = None
) -> dict[str, str]:
    """Cloud admission uses the atomic v25 transaction when PG is active."""
    storage = getattr(settings, "storage_authority", "sqlite")
    if storage != "postgresql":
        return {}
    kwargs: dict[str, str] = {
        "admission_dsn": getattr(settings, "database_url", ""),
        "admission_namespace": str(getattr(stores, "deployment_namespace", "zebra")),
    }
    if idempotency_key:
        kwargs["idempotency_key"] = idempotency_key
    return kwargs

def _post_admission_idempotency(
    settings: object, stores: object, idempotency_key: str | None,
    response: ApiResponse, payload: dict[str, object],
) -> ApiResponse:
    """Local (non-PG) path saves the receipt separately; PG already did."""
    from zebra_agent_api.idempotency import save_idempotent_response
    if idempotency_key is None or getattr(response, 'status_code', 0) != 201:
        return response
    if getattr(settings, 'storage_authority', '') == 'postgresql':
        return response
    store = getattr(stores, "idempotency", None)
    if store is None:
        return response
    return save_idempotent_response(
        store=store, action='session.create',
        idempotency_key=idempotency_key, payload=payload, response=response,
    )

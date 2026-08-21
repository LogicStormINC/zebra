
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

# The default cloud tool surface includes agent.research, so the default
# admission capability set must cover delegating read-only evidence work:
# a parent that cannot hold evidence.read cannot narrow a child to it.
DEFAULT_CAPABILITIES = capability_set(["agent.execute", "evidence.read"])
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
    host_context: HostContextEnvelope | None,
    definition_snapshot_digest: str | None,
    deployment_namespace: str = "zebra",
    frozen_manifest_digest: str | None = None,
) -> TaskBindingSnapshot:
    """Build the binding model without persisting (used by atomic admission).

    Host-bound sessions freeze the Host grant; internal cloud sessions
    (no Host envelope) freeze a deployment-authority binding so they can
    still narrow durable delegations — the capability set never exceeds
    the default admission surface either way.
    """

    if host_context is None:
        grant_digest = hashlib.sha256(
            f"deployment-binding:{deployment_namespace}".encode()
        ).hexdigest()
        host = HostCapabilitySnapshot(
            host_app_id="zebra-internal",
            authority_issuer=f"urn:zebra:deployment:{deployment_namespace}",
            namespace_id=deployment_namespace,
            grant_digest=grant_digest,
            connector_id="zebra-internal",
            connector_profile_revision=1,
            connector_profile_digest=grant_digest,
            manifest_digest=grant_digest,
            capabilities=DEFAULT_CAPABILITIES,
            resource_binding_digest=grant_digest,
            bound_at=datetime.now(UTC),
        )
    else:
        host = HostCapabilitySnapshot(
            host_app_id=host_context.host_app_id,
            authority_issuer=host_context.origin,
            namespace_id=host_context.namespace_id,
            grant_digest=envelope_grant_digest(host_context),
            grant_expires_at=host_context.expires_at,
            connector_id=f"{host_context.host_app_id}-unbound",
            connector_profile_revision=1,
            connector_profile_digest=NO_CONNECTOR_DIGEST,
            manifest_digest=(
                frozen_manifest_digest
                if isinstance(frozen_manifest_digest, str)
                else NO_CONNECTOR_DIGEST
            ),
            capabilities=DEFAULT_CAPABILITIES,
            resource_binding_digest=NO_CONNECTOR_DIGEST,
            bound_at=datetime.now(UTC),
        )
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest=definition_snapshot_digest or NO_CONNECTOR_DIGEST,
        capability_profile_ref="profile/default@1",
        capabilities=DEFAULT_CAPABILITIES,
        resolved_at=datetime.now(UTC),
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
    settings: object,
    stores: object,
    idempotency_key: str | None = None,
    idempotency_request_hash: str | None = None,
    frozen_manifest_digest: str | None = None,
) -> dict[str, str]:
    """Cloud admission uses the atomic v25 transaction when PG is active.

    The canonical request hash is computed ONCE by the caller from the raw
    payload and threaded through verbatim, so the admission transaction
    and the API replay check can never disagree about the same key.
    """

    storage = getattr(settings, "storage_authority", "sqlite")
    if storage != "postgresql":
        return {}
    kwargs: dict[str, str] = {
        "admission_dsn": getattr(settings, "database_url", ""),
        "admission_namespace": str(getattr(stores, "deployment_namespace", "zebra")),
    }
    if idempotency_key:
        kwargs["idempotency_key"] = idempotency_key
    if idempotency_key and idempotency_request_hash:
        kwargs["idempotency_request_hash"] = idempotency_request_hash
    if frozen_manifest_digest:
        kwargs["frozen_manifest_digest"] = frozen_manifest_digest
    return kwargs


def _frozen_manifest_digest(api: object, host_context: object) -> object:
    """ADR-017 admission freeze: the pinned connector's manifest digest.

    Returns None when unbound; a 503 ApiResponse when a pinned manifest
    cannot be frozen — a Host-bound session is never admitted on
    placeholders (fail closed).
    """

    if host_context is None:
        return None
    from zebra_agent_api.host_manifest_freeze import resolve_frozen_manifest
    from zebra_agent_api.responses import service_unavailable

    try:
        frozen = resolve_frozen_manifest(
            getattr(api, "settings", None),
            getattr(api, "stores", None),
            host_context,  # type: ignore[arg-type]
        )
    except ValueError as error:
        return service_unavailable(
            status="host_manifest_unavailable", reason=str(error)[:512]
        )
    if frozen is None:
        return None
    digest = frozen.get("manifestDigest")
    if not isinstance(digest, str) or len(digest) != 64:
        return service_unavailable(
            status="host_manifest_unavailable",
            reason="frozen manifest digest is malformed; failing closed",
        )
    return digest

def _compose_admission(
    api: object,
    host_context: object,
    payload: dict[str, object],
    idempotency_key: str | None,
) -> object:
    """Admission kwargs incl. the frozen manifest digest (or the error)."""

    from zebra_agent_api.idempotency import request_hash
    from zebra_agent_api.responses import ApiResponse

    frozen_digest = _frozen_manifest_digest(api, host_context)
    if isinstance(frozen_digest, ApiResponse):
        return frozen_digest
    assert isinstance(frozen_digest, str) or frozen_digest is None
    return _admission_kwargs(
        getattr(api, "settings", None),
        getattr(api, "stores", None),
        idempotency_key,
        request_hash(payload) if idempotency_key is not None else None,
        frozen_manifest_digest=frozen_digest,
    )


def _post_admission_idempotency(
    settings: object, stores: object, idempotency_key: str | None,
    response: ApiResponse, payload: dict[str, object],
) -> ApiResponse:
    """Sync the stored receipt with the final response body.

    Local (non-PG) path saves the receipt separately; the PG path stored
    it atomically inside admission, so only the response body needs the
    post-composition sync (run-command queueing extends the 201 body).
    """
    if idempotency_key is None or getattr(response, 'status_code', 0) != 201:
        return response
    if getattr(settings, 'storage_authority', '') == 'postgresql':
        from agent_storage.postgres.task_admission import (
            update_idempotency_response,
        )

        update_idempotency_response(
            getattr(settings, "database_url", ""),
            deployment_namespace=str(getattr(stores, "deployment_namespace", "zebra")),
            action="session.create",
            idempotency_key=idempotency_key,
            response_body=response.body,
        )
        return response
    store = getattr(stores, "idempotency", None)
    if store is None:
        return response
    from zebra_agent_api.idempotency import save_idempotent_response

    return save_idempotent_response(
        store=store, action='session.create',
        idempotency_key=idempotency_key, payload=payload, response=response,
    )

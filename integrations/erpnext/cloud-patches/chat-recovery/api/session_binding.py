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
from typing import TYPE_CHECKING
from uuid import UUID

from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
    host_context_digest,
    require_task_host_context,
)
from agent_security.host_grant import VerifiedHostGrant
from agent_storage.postgres.task_admission import load_task_binding, save_task_binding
from zebra_agent_api.responses import ApiResponse, bad_request

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi
    from zebra_agent_api.routes import RouteRequest

# The default cloud tool surface includes agent.research, so the default
# admission capability set must cover delegating read-only evidence work:
# a parent that cannot hold evidence.read cannot narrow a child to it.
DEFAULT_CAPABILITIES = capability_set(["agent.execute", "evidence.read"])
NO_CONNECTOR_DIGEST = "0" * 64


def envelope_grant_digest(envelope: HostContextEnvelope) -> str:
    return host_context_digest(envelope)


def renew_task_binding_snapshot(
    binding: TaskBindingSnapshot,
    host_context: HostContextEnvelope,
    *,
    authority_issuer: str | None = None,
    bound_at: datetime | None = None,
) -> TaskBindingSnapshot:
    """Create the next immutable revision from one freshly verified Grant."""

    host = binding.host_capability
    previous = host.host_context
    if previous is None:
        raise ValueError("Task binding has no renewable Host context")
    renewed_at = bound_at or datetime.now(UTC)
    require_task_host_context(
        binding,
        host_context,
        task_id=binding.task_id,
        now=renewed_at,
        authority_issuer=authority_issuer,
    )
    if (
        not set(host_context.scopes).issubset(previous.scopes)
        # ponytail: Run is a verified request coordinate, not a business ceiling.
        # Its exact target is checked at the command/observer boundary.
        or not {
            ref.key for ref in host_context.resource_refs if ref.resource_type != "run"
        }.issubset(ref.key for ref in previous.resource_refs if ref.resource_type != "run")
        or host_context.policy_version != previous.policy_version
        or any(
            value > previous.limits.model_dump()[name]
            for name, value in host_context.limits.model_dump().items()
        )
    ):
        raise ValueError("Host Grant renewal changed frozen authority ceilings")
    renewed_host = host.model_copy(
        update={
            "grant_digest": host_context_digest(host_context),
            "grant_expires_at": host_context.expires_at,
            "bound_at": renewed_at,
            "host_context": host_context,
        }
    )
    return binding.model_copy(
        update={
            "host_capability": renewed_host,
            "binding_revision": binding.binding_revision + 1,
            "bound_at": renewed_at,
        }
    )


def renew_host_binding_for_command(
    app: object,
    session_id: str,
    verified_host_grant: VerifiedHostGrant | None,
) -> ApiResponse | None:
    """Renew a cloud Task binding before accepting a Host command."""

    if verified_host_grant is None:
        return None
    if not isinstance(verified_host_grant, VerifiedHostGrant):
        return ApiResponse(403, {"status": "host_binding_renewal_rejected"})
    host_context = verified_host_grant.context
    settings = getattr(app, "settings", None)
    if (
        getattr(settings, "deployment", None) != "cloud"
        or getattr(settings, "storage_authority", None) != "postgresql"
    ):
        return None
    stores = getattr(app, "stores", None)
    namespace = getattr(stores, "deployment_namespace", None)
    dsn = getattr(settings, "database_url", None)
    if not isinstance(namespace, str) or not namespace or not isinstance(dsn, str) or not dsn:
        return ApiResponse(503, {"status": "host_binding_renewal_unavailable"})
    try:
        task_id = TaskId(UUID(session_id))
        current = load_task_binding(
            dsn,
            deployment_namespace=namespace,
            task_id=task_id,
        )
    except Exception:
        return ApiResponse(503, {"status": "host_binding_load_failed"})
    if current is None:
        return ApiResponse(409, {"status": "host_binding_missing"})
    try:
        renewed = renew_task_binding_snapshot(
            current,
            host_context,
            authority_issuer=verified_host_grant.authority_issuer,
        )
    except ValueError as exc:
        return ApiResponse(
            403,
            {"status": "host_binding_renewal_rejected", "reason": str(exc)},
        )
    try:
        save_task_binding(
            dsn,
            deployment_namespace=namespace,
            binding=renewed,
            expected_previous_revision=current.binding_revision,
        )
    except ValueError:
        return ApiResponse(409, {"status": "host_binding_revision_conflict"})
    except Exception:
        return ApiResponse(503, {"status": "host_binding_renewal_unavailable"})
    return None


def handle_host_binding_renewal(app: ZebraAgentApi, request: RouteRequest) -> ApiResponse | None:
    """Explicit control-plane renewal, never an execution command or SSE side effect."""
    parts = request.path.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "tasks" or parts[2:] != ["host-binding", "renew"]:
        return None
    if request.method.upper() != "POST":
        return ApiResponse(405, {"status": "method_not_allowed"})
    if request.body:
        return bad_request("binding renewal accepts only an empty body")
    try:
        UUID(parts[1])
    except ValueError:
        return bad_request("Task id must be a UUID")
    verified = request.verified_host_grant
    if (
        not isinstance(verified, VerifiedHostGrant)
        or request.host_context != verified.context
        or "agent.run" not in verified.context.scopes
    ):
        return ApiResponse(403, {"status": "host_binding_renewal_rejected"})
    if app.settings.deployment != "cloud" or app.settings.storage_authority != "postgresql":
        return ApiResponse(409, {"status": "host_binding_renewal_not_supported"})
    error = renew_host_binding_for_command(app, parts[1], verified)
    return error or ApiResponse(200, {"status": "host_binding_renewed"})


def _build_binding_snapshot(
    session_id: object,
    *,
    host_context: HostContextEnvelope | None,
    definition_snapshot_digest: str | None,
    deployment_namespace: str = "zebra",
    frozen_manifest_digest: str | None = None,
    verified_host_grant: VerifiedHostGrant | None = None,
    resolved_connector_profile: object | None = None,
    frozen_host_manifest: object | None = None,
    require_resolved_connector: bool = False,
) -> TaskBindingSnapshot:
    """Build the binding model without persisting (used by atomic admission).

    Host-bound sessions freeze the Host grant; internal cloud sessions
    (no Host envelope) freeze a deployment-authority binding so they can
    still narrow durable delegations — the capability set never exceeds
    the default admission surface either way.
    """

    if require_resolved_connector and (
        resolved_connector_profile is None or frozen_host_manifest is None
    ):
        raise ValueError("published connector profile and frozen manifest are required")
    if (resolved_connector_profile is None) != (frozen_host_manifest is None):
        raise ValueError("connector profile and frozen manifest must resolve together")
    if host_context is None and resolved_connector_profile is not None:
        raise ValueError("resolved connector requires a verified Host context")
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
        if (
            not isinstance(verified_host_grant, VerifiedHostGrant)
            or verified_host_grant.context != host_context
        ):
            raise ValueError("matching verified Host Grant is required")
        profile, manifest = None, None
        bindings_digest = NO_CONNECTOR_DIGEST
        if resolved_connector_profile is not None:
            from agent_core.domain.host_connectors import (
                HostConnectorProfileVersion,
                accepts_new_tasks,
            )
            from agent_integrations.host_tools import HostToolManifest

            if not isinstance(
                resolved_connector_profile, HostConnectorProfileVersion
            ) or not isinstance(frozen_host_manifest, HostToolManifest):
                raise ValueError("typed connector profile and frozen manifest are required")
            profile = HostConnectorProfileVersion.model_validate(
                resolved_connector_profile.model_dump(mode="json")
            )
            manifest = HostToolManifest.from_payload(frozen_host_manifest.to_payload())
            if (
                profile.host_app_id != host_context.host_app_id
                or not accepts_new_tasks(profile.status)
                or manifest.workload_identity != profile.workload_identity_ref
                or manifest.digest != frozen_manifest_digest
            ):
                raise ValueError("published connector profile or frozen manifest drifted")
            # Same native resource-rule canonicalization as HostCapabilitySnapshot,
            # applied to the real parsed wire manifest; no V1 schema conversion.
            bindings_digest = hashlib.sha256(
                json.dumps(
                    [
                        {
                            "tool": tool.name,
                            "bindings": [
                                {
                                    "argumentPointer": rule.argument_pointer,
                                    "resourceType": rule.resource_type,
                                    "required": rule.required,
                                }
                                for rule in manifest.resource_bindings_for(tool.name)
                            ],
                        }
                        for tool in manifest.tools
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        host = HostCapabilitySnapshot(
            host_app_id=host_context.host_app_id,
            authority_issuer=verified_host_grant.authority_issuer,
            namespace_id=host_context.namespace_id,
            grant_digest=envelope_grant_digest(host_context),
            grant_expires_at=host_context.expires_at,
            connector_id=profile.connector_id
            if profile is not None
            else f"{host_context.host_app_id}-unbound",
            connector_profile_revision=profile.profile_revision if profile is not None else 1,
            connector_profile_digest=profile.profile_digest
            if profile is not None
            else NO_CONNECTOR_DIGEST,
            manifest_digest=(
                frozen_manifest_digest
                if isinstance(frozen_manifest_digest, str)
                else NO_CONNECTOR_DIGEST
            ),
            capabilities=DEFAULT_CAPABILITIES,
            resource_binding_digest=bindings_digest,
            bound_at=datetime.now(UTC),
            host_context=host_context,
        )
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest=definition_snapshot_digest or NO_CONNECTOR_DIGEST,
        capability_profile_ref="profile/default@1",
        capabilities=DEFAULT_CAPABILITIES,
        resolved_at=datetime.now(UTC),
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
    if host_context is not None:
        require_task_host_context(
            binding,
            host_context,
            task_id=str(session_id),
            now=datetime.now(UTC),
            authority_issuer=verified_host_grant.authority_issuer if verified_host_grant else None,
        )
    return binding


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
        return service_unavailable(status="host_manifest_unavailable", reason=str(error)[:512])
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
    *,
    strict_composed: bool = False,
) -> object:
    """Admission kwargs incl. the frozen manifest digest (or the error)."""

    from zebra_agent_api.idempotency import request_hash
    from zebra_agent_api.responses import ApiResponse

    if "coverage_admission" in payload:
        from zebra_agent_api.session_payloads import parse_create_session_payload

        preflight = parse_create_session_payload(payload, structural_only=strict_composed)
        if isinstance(preflight, ApiResponse):
            return preflight
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
    settings: object,
    stores: object,
    idempotency_key: str | None,
    response: ApiResponse,
    payload: dict[str, object],
    *,
    public_idempotency_key: str | None = None,
) -> ApiResponse:
    """Sync the stored receipt with the final response body.

    Local (non-PG) path saves the receipt separately; the PG path stored
    it atomically inside admission, so only the response body needs the
    post-composition sync (run-command queueing extends the 201 body).
    """
    if idempotency_key is None or getattr(response, "status_code", 0) != 201:
        return response
    if getattr(settings, "storage_authority", "") == "postgresql":
        from agent_storage.postgres.task_admission import (
            update_idempotency_response,
        )

        response.body["idempotency_key"] = public_idempotency_key or idempotency_key
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
        store=store,
        action="session.create",
        idempotency_key=idempotency_key,
        payload=payload,
        response=response,
        public_idempotency_key=public_idempotency_key,
    )

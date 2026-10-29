"""Admission-side Host manifest freeze (ADR-017).

Cloud admission with a Host envelope and a pinned connector binding
freezes the connector profile revision's manifest ONCE (get-or-fetch);
the frozen digest lands in the Task binding and the Worker consumes
the frozen copy — no live discovery on the execution path. Unbound
namespaces keep the placeholder digest. Failures fail closed: a
Host-bound session whose manifest cannot be frozen is refused, never
admitted on placeholders.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.host_connectors import HostConnectorProfileVersion


class HostManifestFreezeError(ValueError):
    """The pinned connector's manifest could not be frozen; fail closed."""


def resolve_frozen_manifest(
    settings: Any,
    stores: Any,
    host_context: HostContextEnvelope,
) -> dict[str, Any] | None:  # noqa: F722
    """Return the frozen manifest payload for the pinned connector.

    None means the namespace has no connector binding (unbound — the
    binding keeps the placeholder digest). Raises on any pinned-but-
    unfreezable state.
    """

    if getattr(settings, "deployment", "") != "cloud":
        return None
    if getattr(settings, "storage_authority", "") != "postgresql":
        return None
    dsn = getattr(settings, "database_url", "")
    namespace = str(getattr(stores, "deployment_namespace", "zebra"))
    from agent_storage.postgres.host_connectors import (
        PostgresHostConnectorRegistry,
    )
    from agent_storage.postgres.host_manifest_freeze import (
        load_frozen_manifest,
        store_frozen_manifest,
    )

    registry = PostgresHostConnectorRegistry(dsn, deployment_namespace=namespace)
    binding = registry.resolve_binding(host_context.host_app_id, host_context.namespace_id)
    if binding is None:
        return None
    profile = registry.get_profile(
        binding.host_app_id, binding.connector_id, binding.profile_revision
    )
    if profile is None:
        raise HostManifestFreezeError(
            "connector binding references a missing profile revision; failing closed"
        )
    frozen = load_frozen_manifest(
        dsn,
        deployment_namespace=namespace,
        host_app_id=profile.host_app_id,
        connector_id=profile.connector_id,
        profile_revision=profile.profile_revision,
    )
    if frozen is not None:
        from agent_integrations.host_tools import HostToolManifest

        restored = HostToolManifest.from_payload(frozen)
        if profile.manifest_binding_policy == "declared" and restored.binding_policy != "declared":
            raise HostManifestFreezeError("cached manifest binding policy mismatch; failing closed")
        return frozen
    manifest = _discover_once(
        profile,
        host_context,
        getattr(settings, "host_tool_shared_secret", None),
    )
    payload: dict[str, Any] = dict(manifest.to_payload())
    store_frozen_manifest(
        dsn,
        deployment_namespace=namespace,
        manifest_digest=manifest.digest,
        host_app_id=profile.host_app_id,
        connector_id=profile.connector_id,
        profile_revision=profile.profile_revision,
        manifest_payload=payload,
    )
    return payload


def _discover_once(
    profile: Any,
    host_context: HostContextEnvelope,
    configured_secret: str | None,
) -> Any:
    from agent_integrations import ConfiguredHmacHostCredentialResolver
    from agent_integrations.host_tools import HostToolGateway, HostWorkloadIdentity
    from agent_integrations.host_tools.endpoints import profile_gateway_options

    if configured_secret is None or not configured_secret.strip():
        raise HostManifestFreezeError(
            "pinned connector requires a configured Host workload credential"
        )

    identity = HostWorkloadIdentity(
        profile.workload_identity_ref,
        host_context.namespace_id,
        host_context.host_app_id,
    )
    credential = ConfiguredHmacHostCredentialResolver(configured_secret).issue(
        credential_ref=profile.credential_ref,
        workload_identity_ref=profile.workload_identity_ref,
        audience=profile.base_uri,
        scopes=host_context.scopes,
        ttl_seconds=900,
    )
    gateway = HostToolGateway(
        profile.base_uri,
        identity,
        shared_secret=credential.token,
        **profile_gateway_options(profile),
    )
    try:
        return gateway.discover(host_context)
    except Exception as exc:
        raise HostManifestFreezeError(
            f"pinned connector manifest fetch failed; failing closed: {exc}"
        ) from exc


def resolve_admission_profile(
    dsn: str,
    namespace: str,
    context: HostContextEnvelope,
    manifest_digest: str | None,
) -> HostConnectorProfileVersion | None:
    """Refuse registry drift between manifest freeze and atomic Task admission."""
    from agent_integrations.host_tools import HostToolManifest
    from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
    from agent_storage.postgres.host_manifest_freeze import load_frozen_manifest

    registry = PostgresHostConnectorRegistry(dsn, deployment_namespace=namespace)
    binding = registry.resolve_binding(context.host_app_id, context.namespace_id)
    if binding is None:
        if manifest_digest not in (None, "0" * 64):
            raise HostManifestFreezeError("frozen connector binding disappeared")
        return None
    profile = registry.get_profile(
        binding.host_app_id, binding.connector_id, binding.profile_revision
    )
    if not binding.active or profile is None or profile.status.value != "published":
        raise HostManifestFreezeError("connector binding is unavailable")
    frozen = load_frozen_manifest(
        dsn,
        deployment_namespace=namespace,
        host_app_id=profile.host_app_id,
        connector_id=profile.connector_id,
        profile_revision=profile.profile_revision,
    )
    if frozen is None or HostToolManifest.from_payload(frozen).digest != manifest_digest:
        raise HostManifestFreezeError("connector changed after manifest freeze")
    return profile

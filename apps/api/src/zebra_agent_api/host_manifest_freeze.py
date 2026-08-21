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
    binding = registry.resolve_binding(
        host_context.host_app_id, host_context.namespace_id
    )
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
        connector_id=profile.connector_id,
        profile_revision=profile.profile_revision,
    )
    if frozen is not None:
        return frozen
    manifest = _discover_once(profile, host_context)
    payload: dict[str, Any] = dict(manifest.to_payload())
    store_frozen_manifest(
        dsn,
        deployment_namespace=namespace,
        manifest_digest=manifest.digest,
        connector_id=profile.connector_id,
        profile_revision=profile.profile_revision,
        manifest_payload=payload,
    )
    return payload


def _discover_once(
    profile: Any, host_context: HostContextEnvelope
) -> Any:
    from agent_integrations.host_tools import HostToolGateway, HostWorkloadIdentity

    from zebra_agent_api.compat_host_credentials import compat_host_credential

    identity = HostWorkloadIdentity(
        profile.workload_identity_ref,
        host_context.namespace_id,
        host_context.host_app_id,
    )
    credential = compat_host_credential(profile.credential_ref)
    gateway = HostToolGateway(
        profile.base_uri,
        identity,
        shared_secret=credential.token,
    )
    try:
        return gateway.discover(host_context)
    except Exception as exc:
        raise HostManifestFreezeError(
            f"pinned connector manifest fetch failed; failing closed: {exc}"
        ) from exc

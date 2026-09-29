"""Resolve the frozen or pinned Host gateway used by one Worker Task."""

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_core.ports.host_credential_resolver import HostWorkloadCredentialResolverPort
from agent_integrations.host_tools import HostToolGateway, HostToolManifest

NO_MANIFEST_DIGEST = "0" * 64


def frozen_or_discovered_manifest(
    pinned: HostToolGateway,
    host_context: HostContextEnvelope,
    manifest_digest: str | None,
    frozen_manifest_loader: object,
) -> HostToolManifest:
    """Use the admission-frozen manifest when present; drift fails closed."""
    if manifest_digest is None or manifest_digest == NO_MANIFEST_DIGEST:
        return pinned.discover(host_context)
    if not callable(frozen_manifest_loader):
        raise ValueError(
            "binding carries a frozen manifest digest but no loader is wired; failing closed"
        )
    frozen = frozen_manifest_loader(manifest_digest)
    if not isinstance(frozen, dict):
        raise ValueError("frozen Host manifest is missing; failing closed")
    manifest = HostToolManifest.from_payload(frozen)
    if manifest.digest != manifest_digest:
        raise ValueError("frozen Host manifest digest drifted; failing closed")
    object.__setattr__(pinned, "manifest", manifest)
    return manifest


def resolve_pinned_gateway(
    host_context: HostContextEnvelope,
    egress_registry: HostConnectorRegistryPort | None,
    credential_resolver: HostWorkloadCredentialResolverPort | None,
) -> HostToolGateway | None:
    """Resolve a profile-bound Host connector, or preserve the legacy fallback."""
    if egress_registry is None:
        return None
    from zebra_agent_worker.host_egress import HostEgressResolver, build_pinned_host_gateway

    resolver = HostEgressResolver(egress_registry, credential_resolver)
    pinned = resolver.resolve(host_context)
    if pinned is None:
        return None
    if credential_resolver is None:
        raise ValueError(
            "pinned connector requires a configured Host workload credential; failing closed"
        )
    credential = resolver.issue_credential(pinned, host_context)
    return build_pinned_host_gateway(pinned, host_context, credential)

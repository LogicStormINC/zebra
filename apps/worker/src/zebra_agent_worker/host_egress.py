"""Pinned Host egress from immutable connector profiles (AL-HOST-EGRESS-01).

The P0.2 implementation side: instead of mutable deployment-level
``ZEBRA_HOST_TOOL_*`` globals, the Worker resolves one
``host_app_id + namespace_id`` to an immutable Connector Profile revision
through the operator-owned registry, issues an ephemeral credential via
``HostWorkloadCredentialResolverPort`` (memory-only), and builds the Host
gateway from the pinned profile. Revoked or missing profiles fail closed;
deprecated profiles keep serving already-bound Tasks per the lifecycle
table. The legacy global-env path remains the fallback until
``AL-LEGACY-REMOVAL-01``.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.host_connectors import (
    HostConnectorProfileVersion,
    HostConnectorStatus,
)
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_core.ports.host_credential_resolver import (
    EphemeralHostCredential,
    HostWorkloadCredentialResolverPort,
)
from agent_integrations.host_tools import HostToolGateway, HostWorkloadIdentity

EGRESS_CREDENTIAL_TTL_SECONDS = 900


@dataclass(frozen=True)
class PinnedHostConnector:
    """Everything the Worker needs from one pinned binding + profile."""

    profile: HostConnectorProfileVersion
    binding_revision: int

    @property
    def endpoint(self) -> str:
        return self.profile.base_uri

    @property
    def deprecated(self) -> bool:
        return self.profile.status is HostConnectorStatus.DEPRECATED


class HostEgressResolver:
    """Resolve one Host namespace to its pinned, immutable egress profile."""

    def __init__(
        self,
        registry: HostConnectorRegistryPort,
        credentials: HostWorkloadCredentialResolverPort,
    ) -> None:
        self._registry = registry
        self._credentials = credentials

    def resolve(self, host_context: HostContextEnvelope) -> PinnedHostConnector | None:
        """Return the pinned connector, ``None`` when no binding exists."""

        binding = self._registry.resolve_binding(
            host_context.host_app_id,
            host_context.namespace_id,
        )
        if binding is None:
            return None
        profile = self._registry.get_profile(
            binding.host_app_id,
            binding.connector_id,
            binding.profile_revision,
        )
        if profile is None:
            raise ValueError(
                "connector binding references a missing profile revision; failing closed"
            )
        if profile.status is HostConnectorStatus.REVOKED:
            raise ValueError("connector profile is revoked; failing closed")
        return PinnedHostConnector(
            profile=profile,
            binding_revision=binding.binding_revision,
        )

    def issue_credential(
        self,
        connector: PinnedHostConnector,
        host_context: HostContextEnvelope,
    ) -> EphemeralHostCredential:
        """Issue a memory-only credential for the pinned profile."""

        return self._credentials.issue(
            credential_ref=connector.profile.credential_ref,
            workload_identity_ref=connector.profile.workload_identity_ref,
            audience=connector.profile.base_uri,
            scopes=host_context.scopes,
            ttl_seconds=EGRESS_CREDENTIAL_TTL_SECONDS,
        )


def build_pinned_host_gateway(
    connector: PinnedHostConnector,
    host_context: HostContextEnvelope,
    credential: EphemeralHostCredential,
) -> HostToolGateway:
    """Build the Host gateway from the pinned profile and ephemeral credential.

    ponytail: during the legacy window the ephemeral token feeds the
    gateway's HMAC header path; OAuth workload identity / mTLS adapters
    replace the transport without changing this seam.
    """

    identity = HostWorkloadIdentity(
        connector.profile.workload_identity_ref,
        host_context.namespace_id,
        host_context.host_app_id,
    )
    return HostToolGateway(
        connector.endpoint,
        identity,
        shared_secret=credential.token,
    )

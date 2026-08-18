"""Registry Port for outbound Host connector profiles and bindings."""

from __future__ import annotations

from typing import Protocol

from agent_core.domain.host_connectors import (
    HostConnectorBinding,
    HostConnectorProfileVersion,
)


class HostConnectorRegistryPort(Protocol):
    """Resolve and manage outbound connector profiles.

    Write access belongs to Zebra operators only; ordinary HostGrants can
    never mutate this registry (plan section 12). Implementations must keep
    profile revisions immutable and namespace-isolated.
    """

    def get_profile(
        self,
        host_app_id: str,
        connector_id: str,
        profile_revision: int,
    ) -> HostConnectorProfileVersion | None: ...

    def resolve_binding(self, host_app_id: str, namespace_id: str) -> HostConnectorBinding | None:
        """Return the active binding pinning one Host namespace to a profile."""

    def publish_profile(
        self,
        profile: HostConnectorProfileVersion,
    ) -> HostConnectorProfileVersion:
        """Publish a new immutable profile revision; returns the stored value."""

    def bind(
        self,
        binding: HostConnectorBinding,
    ) -> HostConnectorBinding:
        """Pin a namespace to a connector profile revision via CAS."""

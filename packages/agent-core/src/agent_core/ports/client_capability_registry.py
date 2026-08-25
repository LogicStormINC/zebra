"""Registry port for published frontend capability profiles and bindings."""

from typing import Protocol
from uuid import UUID

from agent_core.domain.client_capabilities import (
    FrontendCapabilityBinding,
    FrontendCapabilityProfileVersion,
    ProfileLifecycle,
)


class ClientCapabilityRegistryPort(Protocol):
    def publish_profile(self, profile: FrontendCapabilityProfileVersion) -> None:
        """Insert one immutable revision; insert-only, never update."""

    def get_profile(
        self, frontend_app_id: str, revision: int
    ) -> FrontendCapabilityProfileVersion | None: ...

    def get_latest_profile(
        self, frontend_app_id: str
    ) -> FrontendCapabilityProfileVersion | None: ...

    def set_lifecycle(
        self,
        frontend_app_id: str,
        revision: int,
        lifecycle: ProfileLifecycle,
    ) -> None:
        """Deprecate or revoke a revision; publish→lifecycle transitions only."""

    def save_binding(
        self, binding: FrontendCapabilityBinding, *, expected_binding_revision: int
    ) -> FrontendCapabilityBinding:
        """CAS on binding_revision; zero rows written on stale expectations."""

    def get_binding(self, binding_id: UUID) -> FrontendCapabilityBinding | None: ...

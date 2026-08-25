"""Frontend capability profile application services (ADR-CLIENT-01).

Pure application services over the capability registry port: publish
validation, versioning, namespace binding and lifecycle. Composition
happens in the API; nothing here touches HTTP or storage directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.client_capabilities import (
    ClientCapabilityError,
    FrontendCapabilityBinding,
    FrontendCapabilityProfileVersion,
    ProfileLifecycle,
    validate_profile_for_publish,
)
from agent_core.ports.client_capability_registry import ClientCapabilityRegistryPort


class FrontendProfileServiceError(ValueError):
    pass


@dataclass(frozen=True)
class ProfilePublication:
    frontend_app_id: str
    revision: int
    profile_digest: str
    lifecycle: ProfileLifecycle


class FrontendProfileService:
    """Management-plane operations; callers must be platform operators."""

    def __init__(self, registry: ClientCapabilityRegistryPort) -> None:
        self._registry = registry

    def validate(
        self, profile: FrontendCapabilityProfileVersion
    ) -> FrontendCapabilityProfileVersion:
        validate_profile_for_publish(profile)
        return profile

    def publish(
        self, profile: FrontendCapabilityProfileVersion
    ) -> ProfilePublication:
        self.validate(profile)
        self._registry.publish_profile(profile)
        return ProfilePublication(
            frontend_app_id=profile.frontend_app_id,
            revision=profile.revision,
            profile_digest=profile.profile_digest,
            lifecycle=profile.lifecycle,
        )

    def publish_version(
        self,
        frontend_app_id: str,
        profile: FrontendCapabilityProfileVersion,
    ) -> ProfilePublication:
        latest = self._registry.get_latest_profile(frontend_app_id)
        if latest is not None and profile.revision <= latest.revision:
            raise FrontendProfileServiceError(
                "new versions must increase the revision monotonically"
            )
        return self.publish(profile)

    def bind(
        self,
        *,
        host_app_id: str,
        namespace_id: str,
        frontend_app_id: str,
        revision: int,
        profile_digest: str,
        expected_binding_revision: int = 0,
    ) -> FrontendCapabilityBinding:
        profile = self._registry.get_profile(frontend_app_id, revision)
        if profile is None:
            raise FrontendProfileServiceError("profile revision is not published")
        if profile.profile_digest != profile_digest:
            raise ClientCapabilityError(
                "profile digest drift; binding fails closed"
            )
        binding_revision = expected_binding_revision + 1
        binding = FrontendCapabilityBinding(
            binding_id=uuid4(),
            deployment_namespace=self._namespace_of(registry=self._registry),
            host_app_id=host_app_id,
            namespace_id=namespace_id,
            frontend_app_id=frontend_app_id,
            revision=revision,
            profile_digest=profile_digest,
            binding_revision=binding_revision,
            bound_at=datetime.now(UTC),
        )
        return self._registry.save_binding(
            binding, expected_binding_revision=expected_binding_revision
        )

    def deprecate(self, frontend_app_id: str, revision: int) -> None:
        self._registry.set_lifecycle(
            frontend_app_id, revision, ProfileLifecycle.DEPRECATED
        )

    def revoke(self, frontend_app_id: str, revision: int) -> None:
        self._registry.set_lifecycle(
            frontend_app_id, revision, ProfileLifecycle.REVOKED
        )

    def get(self, frontend_app_id: str, revision: int | None = None) -> ProfilePublication:
        profile = (
            self._registry.get_profile(frontend_app_id, revision)
            if revision is not None
            else self._registry.get_latest_profile(frontend_app_id)
        )
        if profile is None:
            raise FrontendProfileServiceError("profile not found")
        return ProfilePublication(
            frontend_app_id=profile.frontend_app_id,
            revision=profile.revision,
            profile_digest=profile.profile_digest,
            lifecycle=profile.lifecycle,
        )

    @staticmethod
    def _namespace_of(*, registry: object) -> str:
        namespace = getattr(registry, "deployment_namespace", None)
        if not isinstance(namespace, str) or not namespace.strip():
            raise FrontendProfileServiceError(
                "capability registry must expose its deployment namespace"
            )
        return namespace

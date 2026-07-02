from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_core.domain import ArtifactAccessDescriptor

from agent_security.artifact_access import (
    classify_artifact_access,
    required_policy_profile_for_artifact_access,
)
from agent_security.policy import PolicyProfile


@dataclass(frozen=True)
class ArtifactAccessProjection:
    access_class: str
    required_policy_profile: str
    session_policy_profile: str

    @property
    def allowed(self) -> bool:
        return _policy_rank(self.session_policy_profile) >= _policy_rank(
            self.required_policy_profile
        )


class SupportsRequiredPolicyProfile(Protocol):
    @property
    def required_policy_profile(self) -> str: ...


class SupportsArtifactControlAccessFields(SupportsRequiredPolicyProfile, Protocol):
    @property
    def access_class(self) -> str: ...


class SupportsArtifactAccessFields(SupportsArtifactControlAccessFields, Protocol):
    @property
    def session_policy_profile(self) -> str: ...

    @property
    def allowed(self) -> bool: ...


def build_artifact_access_projection(
    descriptor: ArtifactAccessDescriptor,
    *,
    session_policy_profile: str,
) -> ArtifactAccessProjection:
    access_class = classify_artifact_access(descriptor)
    return ArtifactAccessProjection(
        access_class=access_class.value,
        required_policy_profile=required_policy_profile_for_artifact_access(access_class),
        session_policy_profile=session_policy_profile,
    )


def build_session_artifact_access_projection(
    *,
    kind: str,
    mime_type: str | None,
    uri: str | None,
    preview_redacted: bool,
    preview_truncated: bool,
    session_policy_profile: str,
) -> ArtifactAccessProjection:
    return build_artifact_access_projection(
        ArtifactAccessDescriptor(
            kind=kind,
            mime_type=mime_type,
            uri=uri,
            preview_redacted=preview_redacted,
            preview_truncated=preview_truncated,
        ),
        session_policy_profile=session_policy_profile,
    )


def serialize_artifact_access_projection(
    projection: ArtifactAccessProjection,
) -> dict[str, object]:
    return {
        "class": projection.access_class,
        "required_policy_profile": projection.required_policy_profile,
        "session_policy_profile": projection.session_policy_profile,
        "allowed": projection.allowed,
    }


def serialize_session_artifact_access_projection(
    projection: ArtifactAccessProjection,
) -> dict[str, object]:
    return serialize_artifact_access_projection(projection)


def serialize_artifact_access_snapshot_attachment(
    projection: ArtifactAccessProjection,
) -> dict[str, object]:
    return {"access": serialize_session_artifact_access_projection(projection)}


def artifact_policy_denied_reason(
    projection: SupportsRequiredPolicyProfile,
    *,
    action: str,
) -> str:
    return f"artifact_{action}_requires_{projection.required_policy_profile}_policy"


def serialize_artifact_control_access_fields(
    projection: SupportsArtifactControlAccessFields,
) -> dict[str, object]:
    return {
        "access_class": projection.access_class,
        "required_policy_profile": projection.required_policy_profile,
    }


def serialize_artifact_control_success_outcome_fields(
    projection: SupportsArtifactControlAccessFields,
    *,
    status: str,
    lifecycle: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "status": status,
        **serialize_artifact_control_access_fields(projection),
        "lifecycle": lifecycle,
    }


def serialize_artifact_access_outcome_fields(
    projection: SupportsArtifactAccessFields,
    *,
    status: str,
    reason: str,
) -> dict[str, object]:
    return {
        "status": status,
        "reason": reason,
        "access": {
            "class": projection.access_class,
            "required_policy_profile": projection.required_policy_profile,
            "session_policy_profile": projection.session_policy_profile,
            "allowed": projection.allowed,
        },
    }


def serialize_artifact_control_outcome_fields(
    *,
    status: str,
    reason: str,
) -> dict[str, object]:
    return {
        "status": status,
        "reason": reason,
    }


def policy_rank(policy_profile: str) -> int:
    return _policy_rank(policy_profile)


def _policy_rank(policy_profile: str) -> int:
    order = {
        PolicyProfile.READ_ONLY.value: 0,
        PolicyProfile.WORKSPACE_WRITE.value: 1,
        PolicyProfile.FULL_ACCESS.value: 2,
    }
    return order.get(policy_profile, 0)

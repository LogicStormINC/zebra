from __future__ import annotations

from dataclasses import dataclass

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


def serialize_artifact_access_projection(
    projection: ArtifactAccessProjection,
) -> dict[str, object]:
    return {
        "class": projection.access_class,
        "required_policy_profile": projection.required_policy_profile,
        "session_policy_profile": projection.session_policy_profile,
        "allowed": projection.allowed,
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

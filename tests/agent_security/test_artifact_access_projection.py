from agent_core.domain import ArtifactAccessDescriptor
from agent_security import (
    ArtifactAccessProjection,
    PolicyProfile,
    build_artifact_access_projection,
    policy_rank,
    serialize_artifact_access_projection,
)


def test_build_artifact_access_projection_for_operator_safe_payload() -> None:
    projection = build_artifact_access_projection(
        ArtifactAccessDescriptor(
            kind="tool_output",
            mime_type="text/plain",
            uri="file:///tmp/pytest.log",
        ),
        session_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
    )

    assert projection == ArtifactAccessProjection(
        access_class="operator_safe",
        required_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
        session_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
    )
    assert projection.allowed is True


def test_build_artifact_access_projection_for_sensitive_payload() -> None:
    projection = build_artifact_access_projection(
        ArtifactAccessDescriptor(
            kind="tool_output",
            mime_type="application/json",
            uri="file:///tmp/result.json",
        ),
        session_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
    )

    assert projection == ArtifactAccessProjection(
        access_class="sensitive",
        required_policy_profile=PolicyProfile.FULL_ACCESS.value,
        session_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
    )
    assert projection.allowed is False


def test_serialize_artifact_access_projection_returns_machine_readable_payload() -> None:
    projection = ArtifactAccessProjection(
        access_class="restricted",
        required_policy_profile=PolicyProfile.FULL_ACCESS.value,
        session_policy_profile=PolicyProfile.FULL_ACCESS.value,
    )

    assert serialize_artifact_access_projection(projection) == {
        "class": "restricted",
        "required_policy_profile": "full_access",
        "session_policy_profile": "full_access",
        "allowed": True,
    }


def test_policy_rank_orders_known_profiles_and_fails_closed() -> None:
    assert policy_rank(PolicyProfile.READ_ONLY.value) == 0
    assert policy_rank(PolicyProfile.WORKSPACE_WRITE.value) == 1
    assert policy_rank(PolicyProfile.FULL_ACCESS.value) == 2
    assert policy_rank("unknown-profile") == 0

from agent_core.domain import ArtifactAccessDescriptor
from agent_security import (
    ArtifactAccessProjection,
    PolicyProfile,
    artifact_policy_denied_reason,
    build_artifact_access_projection,
    build_session_artifact_access_projection,
    policy_rank,
    serialize_artifact_access_outcome_fields,
    serialize_artifact_access_projection,
    serialize_artifact_access_snapshot_attachment,
    serialize_artifact_control_access_fields,
    serialize_artifact_control_outcome_fields,
    serialize_artifact_control_success_outcome_fields,
    serialize_session_artifact_access_projection,
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


def test_build_session_artifact_access_projection_reuses_descriptor_assembly() -> None:
    projection = build_session_artifact_access_projection(
        kind="tool_output",
        mime_type="application/json",
        uri="file:///tmp/result.json",
        preview_redacted=False,
        preview_truncated=False,
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


def test_serialize_session_artifact_access_projection_reuses_shared_payload() -> None:
    projection = ArtifactAccessProjection(
        access_class="operator_safe",
        required_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
        session_policy_profile=PolicyProfile.FULL_ACCESS.value,
    )

    assert serialize_session_artifact_access_projection(projection) == {
        "class": "operator_safe",
        "required_policy_profile": "workspace_write",
        "session_policy_profile": "full_access",
        "allowed": True,
    }


def test_serialize_artifact_access_snapshot_attachment_reuses_session_snapshot() -> None:
    projection = ArtifactAccessProjection(
        access_class="operator_safe",
        required_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
        session_policy_profile=PolicyProfile.FULL_ACCESS.value,
    )

    assert serialize_artifact_access_snapshot_attachment(projection) == {
        "access": {
            "class": "operator_safe",
            "required_policy_profile": "workspace_write",
            "session_policy_profile": "full_access",
            "allowed": True,
        },
    }


def test_artifact_policy_denied_reason_reuses_required_profile() -> None:
    projection = ArtifactAccessProjection(
        access_class="sensitive",
        required_policy_profile=PolicyProfile.FULL_ACCESS.value,
        session_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
    )

    assert artifact_policy_denied_reason(projection, action="read") == (
        "artifact_read_requires_full_access_policy"
    )


def test_serialize_artifact_control_access_fields_reuses_access_projection() -> None:
    projection = ArtifactAccessProjection(
        access_class="operator_safe",
        required_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
        session_policy_profile=PolicyProfile.FULL_ACCESS.value,
    )

    assert serialize_artifact_control_access_fields(projection) == {
        "access_class": "operator_safe",
        "required_policy_profile": "workspace_write",
    }


def test_serialize_artifact_access_outcome_fields_reuses_access_projection() -> None:
    projection = ArtifactAccessProjection(
        access_class="sensitive",
        required_policy_profile=PolicyProfile.FULL_ACCESS.value,
        session_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
    )

    assert serialize_artifact_access_outcome_fields(
        projection,
        status="artifact_policy_denied",
        reason="artifact_read_requires_full_access_policy",
    ) == {
        "status": "artifact_policy_denied",
        "reason": "artifact_read_requires_full_access_policy",
        "access": {
            "class": "sensitive",
            "required_policy_profile": "full_access",
            "session_policy_profile": "workspace_write",
            "allowed": False,
        },
    }


def test_serialize_artifact_control_outcome_fields_reuses_status_and_reason() -> None:
    assert serialize_artifact_control_outcome_fields(
        status="artifact_unavailable",
        reason="artifact_uses_external_reference",
    ) == {
        "status": "artifact_unavailable",
        "reason": "artifact_uses_external_reference",
    }


def test_serialize_artifact_control_success_outcome_fields_reuses_status_and_access() -> None:
    projection = ArtifactAccessProjection(
        access_class="operator_safe",
        required_policy_profile=PolicyProfile.WORKSPACE_WRITE.value,
        session_policy_profile=PolicyProfile.FULL_ACCESS.value,
    )

    assert serialize_artifact_control_success_outcome_fields(
        projection,
        status="pruned",
        lifecycle={"status": "pruned", "pruned_at": "2026-07-02T00:00:00Z"},
    ) == {
        "status": "pruned",
        "access_class": "operator_safe",
        "required_policy_profile": "workspace_write",
        "lifecycle": {"status": "pruned", "pruned_at": "2026-07-02T00:00:00Z"},
    }


def test_policy_rank_orders_known_profiles_and_fails_closed() -> None:
    assert policy_rank(PolicyProfile.READ_ONLY.value) == 0
    assert policy_rank(PolicyProfile.WORKSPACE_WRITE.value) == 1
    assert policy_rank(PolicyProfile.FULL_ACCESS.value) == 2
    assert policy_rank("unknown-profile") == 0

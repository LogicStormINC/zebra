from agent_security import (
    ArtifactAccessProjection,
    build_artifact_control_audit_metadata,
)


def test_build_artifact_control_audit_metadata_for_denied_result() -> None:
    projection = ArtifactAccessProjection(
        access_class="sensitive",
        required_policy_profile="full_access",
        session_policy_profile="workspace_write",
    )

    assert build_artifact_control_audit_metadata(
        artifact_id="tool-run:5",
        result_status="artifact_prune_denied",
        projection=projection,
        extra={"payload_artifact_id": "2d77d7ca-1ee7-46b4-8d0d-51e32c8c0cff"},
    ) == {
        "artifact_id": "tool-run:5",
        "result_status": "artifact_prune_denied",
        "access_class": "sensitive",
        "required_policy_profile": "full_access",
        "session_policy_profile": "workspace_write",
        "payload_artifact_id": "2d77d7ca-1ee7-46b4-8d0d-51e32c8c0cff",
    }


def test_build_artifact_control_audit_metadata_for_success_result() -> None:
    projection = ArtifactAccessProjection(
        access_class="operator_safe",
        required_policy_profile="workspace_write",
        session_policy_profile="workspace_write",
    )

    assert build_artifact_control_audit_metadata(
        artifact_id="tool-run:5",
        result_status="pruned",
        projection=projection,
        extra={
            "payload_artifact_id": "2d77d7ca-1ee7-46b4-8d0d-51e32c8c0cff",
            "lifecycle_status": "pruned",
        },
    ) == {
        "artifact_id": "tool-run:5",
        "result_status": "pruned",
        "access_class": "operator_safe",
        "required_policy_profile": "workspace_write",
        "session_policy_profile": "workspace_write",
        "payload_artifact_id": "2d77d7ca-1ee7-46b4-8d0d-51e32c8c0cff",
        "lifecycle_status": "pruned",
    }


def test_build_artifact_control_audit_metadata_for_unavailable_result() -> None:
    assert build_artifact_control_audit_metadata(
        artifact_id="tool-run:5",
        result_status="artifact_prune_unavailable",
        unavailable_reason="artifact_uses_external_reference",
    ) == {
        "artifact_id": "tool-run:5",
        "result_status": "artifact_prune_unavailable",
        "unavailable_reason": "artifact_uses_external_reference",
    }

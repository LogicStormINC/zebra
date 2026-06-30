from agent_security import (
    ArtifactAccessProjection,
    build_artifact_access_audit_metadata,
)


def test_build_artifact_access_audit_metadata_for_allowed_payload() -> None:
    projection = ArtifactAccessProjection(
        access_class="operator_safe",
        required_policy_profile="workspace_write",
        session_policy_profile="workspace_write",
    )

    assert build_artifact_access_audit_metadata(
        projection,
        artifact_id="tool-run:5",
        result_status="ok",
        retrieval_status="payload_available",
        extra={"size_bytes": 13},
    ) == {
        "artifact_id": "tool-run:5",
        "access_class": "operator_safe",
        "required_policy_profile": "workspace_write",
        "session_policy_profile": "workspace_write",
        "result_status": "ok",
        "retrieval_status": "payload_available",
        "size_bytes": 13,
    }


def test_build_artifact_access_audit_metadata_for_denied_payload() -> None:
    projection = ArtifactAccessProjection(
        access_class="sensitive",
        required_policy_profile="full_access",
        session_policy_profile="workspace_write",
    )

    assert build_artifact_access_audit_metadata(
        projection,
        artifact_id="tool-run:5",
        result_status="artifact_access_denied",
        retrieval_status="access_denied",
        reason="artifact_read_requires_full_access_policy",
    ) == {
        "artifact_id": "tool-run:5",
        "access_class": "sensitive",
        "required_policy_profile": "full_access",
        "session_policy_profile": "workspace_write",
        "result_status": "artifact_access_denied",
        "retrieval_status": "access_denied",
        "reason": "artifact_read_requires_full_access_policy",
    }


def test_build_artifact_access_audit_metadata_for_prune_result_without_retrieval() -> None:
    projection = ArtifactAccessProjection(
        access_class="operator_safe",
        required_policy_profile="workspace_write",
        session_policy_profile="workspace_write",
    )

    assert build_artifact_access_audit_metadata(
        projection,
        artifact_id="tool-run:5",
        result_status="pruned",
        extra={
            "payload_artifact_id": "2d77d7ca-1ee7-46b4-8d0d-51e32c8c0cff",
            "lifecycle_status": "pruned",
        },
    ) == {
        "artifact_id": "tool-run:5",
        "access_class": "operator_safe",
        "required_policy_profile": "workspace_write",
        "session_policy_profile": "workspace_write",
        "result_status": "pruned",
        "payload_artifact_id": "2d77d7ca-1ee7-46b4-8d0d-51e32c8c0cff",
        "lifecycle_status": "pruned",
    }

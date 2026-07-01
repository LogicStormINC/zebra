from agent_core.domain import ArtifactAccessClass, ArtifactAccessDescriptor
from agent_security import (
    PolicyProfile,
    classify_artifact_access,
    required_policy_profile_for_artifact_access,
)


def test_assistant_message_is_operator_safe() -> None:
    access_class = classify_artifact_access(
        ArtifactAccessDescriptor(kind="assistant_message")
    )

    assert access_class is ArtifactAccessClass.OPERATOR_SAFE
    assert required_policy_profile_for_artifact_access(access_class) == (
        PolicyProfile.WORKSPACE_WRITE.value
    )


def test_local_text_tool_output_is_operator_safe() -> None:
    access_class = classify_artifact_access(
        ArtifactAccessDescriptor(
            kind="tool_output",
            mime_type="text/plain",
            uri="file:///tmp/pytest.log",
        )
    )

    assert access_class is ArtifactAccessClass.OPERATOR_SAFE


def test_redacted_preview_fails_closed_to_sensitive() -> None:
    access_class = classify_artifact_access(
        ArtifactAccessDescriptor(
            kind="tool_output",
            mime_type="text/plain",
            preview_redacted=True,
        )
    )

    assert access_class is ArtifactAccessClass.SENSITIVE
    assert required_policy_profile_for_artifact_access(access_class) == (
        PolicyProfile.FULL_ACCESS.value
    )


def test_non_text_tool_output_is_sensitive() -> None:
    access_class = classify_artifact_access(
        ArtifactAccessDescriptor(
            kind="tool_output",
            mime_type="application/json",
            uri="file:///tmp/result.json",
        )
    )

    assert access_class is ArtifactAccessClass.SENSITIVE


def test_external_reference_is_restricted() -> None:
    access_class = classify_artifact_access(
        ArtifactAccessDescriptor(
            kind="tool_output",
            mime_type="text/plain",
            uri="https://example.test/result.txt",
        )
    )

    assert access_class is ArtifactAccessClass.RESTRICTED
    assert required_policy_profile_for_artifact_access(access_class) == (
        PolicyProfile.FULL_ACCESS.value
    )


def test_unknown_kind_fails_closed_to_sensitive() -> None:
    access_class = classify_artifact_access(
        ArtifactAccessDescriptor(
            kind="custom_export",
            mime_type="text/plain",
        )
    )

    assert access_class is ArtifactAccessClass.SENSITIVE

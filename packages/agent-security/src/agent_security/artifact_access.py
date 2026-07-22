from urllib.parse import urlparse

from agent_core.domain import ArtifactAccessClass, ArtifactAccessDescriptor

from agent_security.policy import PolicyProfile

_LOCAL_FILE_URI_SCHEME = "file"
_LOCAL_ARTIFACT_URI_SCHEME = "artifact"
_LOCAL_URI_SCHEMES = frozenset({_LOCAL_FILE_URI_SCHEME, _LOCAL_ARTIFACT_URI_SCHEME})
_OPERATOR_SAFE_KINDS = frozenset({"assistant_message"})
_LOCAL_TEXT_MIME_PREFIX = "text/"


def classify_artifact_access(
    descriptor: ArtifactAccessDescriptor,
) -> ArtifactAccessClass:
    if _is_restricted_external_reference(descriptor.uri):
        return ArtifactAccessClass.RESTRICTED
    if descriptor.preview_redacted:
        return ArtifactAccessClass.SENSITIVE
    if descriptor.kind in _OPERATOR_SAFE_KINDS:
        return ArtifactAccessClass.OPERATOR_SAFE
    if descriptor.kind == "tool_output" and _is_local_text_payload(descriptor.mime_type):
        return ArtifactAccessClass.OPERATOR_SAFE
    return ArtifactAccessClass.SENSITIVE


def required_policy_profile_for_artifact_access(
    access_class: ArtifactAccessClass,
) -> str:
    if access_class is ArtifactAccessClass.OPERATOR_SAFE:
        return PolicyProfile.WORKSPACE_WRITE.value
    return PolicyProfile.FULL_ACCESS.value


def _is_restricted_external_reference(uri: str | None) -> bool:
    if uri is None:
        return False
    parsed = urlparse(uri)
    return bool(parsed.scheme) and parsed.scheme not in _LOCAL_URI_SCHEMES


def _is_local_text_payload(mime_type: str | None) -> bool:
    return mime_type is not None and mime_type.startswith(_LOCAL_TEXT_MIME_PREFIX)

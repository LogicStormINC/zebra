from __future__ import annotations

from collections.abc import Mapping

from agent_security.artifact_access_projection import ArtifactAccessProjection


def build_artifact_access_audit_metadata(
    projection: ArtifactAccessProjection,
    *,
    artifact_id: str,
    result_status: str,
    retrieval_status: str | None = None,
    reason: str | None = None,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "artifact_id": artifact_id,
        "access_class": projection.access_class,
        "required_policy_profile": projection.required_policy_profile,
        "session_policy_profile": projection.session_policy_profile,
        "result_status": result_status,
    }
    if retrieval_status is not None:
        metadata["retrieval_status"] = retrieval_status
    if reason is not None:
        metadata["reason"] = reason
    if extra is not None:
        metadata.update(dict(extra))
    return metadata

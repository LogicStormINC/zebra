from __future__ import annotations

from collections.abc import Mapping

from agent_security.artifact_access_projection import ArtifactAccessProjection


def build_artifact_audit_metadata(
    *,
    artifact_id: str,
    result_status: str,
    projection: ArtifactAccessProjection | None = None,
    retrieval_status: str | None = None,
    reason: str | None = None,
    reason_field: str = "reason",
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "artifact_id": artifact_id,
        "result_status": result_status,
    }
    if projection is not None:
        metadata.update(
            {
                "access_class": projection.access_class,
                "required_policy_profile": projection.required_policy_profile,
                "session_policy_profile": projection.session_policy_profile,
            }
        )
    if retrieval_status is not None:
        metadata["retrieval_status"] = retrieval_status
    if reason is not None:
        metadata[reason_field] = reason
    if extra is not None:
        metadata.update(dict(extra))
    return metadata

from __future__ import annotations

from collections.abc import Mapping

from agent_security.artifact_access_projection import ArtifactAccessProjection
from agent_security.artifact_audit_metadata import build_artifact_audit_metadata


def build_artifact_access_audit_metadata(
    projection: ArtifactAccessProjection,
    *,
    artifact_id: str,
    result_status: str,
    retrieval_status: str | None = None,
    reason: str | None = None,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return build_artifact_audit_metadata(
        artifact_id=artifact_id,
        result_status=result_status,
        projection=projection,
        retrieval_status=retrieval_status,
        reason=reason,
        extra=extra,
    )

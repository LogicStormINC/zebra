from __future__ import annotations

from collections.abc import Mapping

from agent_security.artifact_access_projection import ArtifactAccessProjection
from agent_security.artifact_audit_metadata import build_artifact_audit_metadata


def build_artifact_control_audit_metadata(
    *,
    artifact_id: str,
    result_status: str,
    projection: ArtifactAccessProjection | None = None,
    unavailable_reason: str | None = None,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return build_artifact_audit_metadata(
        artifact_id=artifact_id,
        result_status=result_status,
        projection=projection,
        reason=unavailable_reason,
        reason_field="unavailable_reason",
        extra=extra,
    )

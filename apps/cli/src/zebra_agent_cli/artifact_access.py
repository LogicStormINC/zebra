from __future__ import annotations

from pathlib import Path

from agent_security import (
    ArtifactAccessProjection,
    artifact_policy_denied_reason,
    serialize_artifact_access_outcome_fields,
    serialize_artifact_access_snapshot_attachment,
    serialize_artifact_control_outcome_fields,
    serialize_artifact_control_success_outcome_fields,
)

ArtifactAccessContext = ArtifactAccessProjection

def build_artifact_access_result(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
    status: str,
    reason: str,
    access: ArtifactAccessContext,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "database": str(database_path),
        **serialize_artifact_access_outcome_fields(
            access,
            status=status,
            reason=reason,
        ),
    }


def build_artifact_policy_denied_result(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
    status: str,
    action: str,
    access: ArtifactAccessContext,
) -> dict[str, object]:
    return build_artifact_access_result(
        database_path=database_path,
        session_id=session_id,
        artifact_id=artifact_id,
        status=status,
        reason=artifact_policy_denied_reason(access, action=action),
        access=access,
    )


def build_artifact_unavailable_result(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
    reason: str,
    access: ArtifactAccessContext,
) -> dict[str, object]:
    return build_artifact_access_result(
        database_path=database_path,
        session_id=session_id,
        artifact_id=artifact_id,
        status="artifact_unavailable",
        reason=reason,
        access=access,
    )


def build_artifact_control_denied_result(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
    status: str,
    action: str,
    access: ArtifactAccessContext,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "database": str(database_path),
        **serialize_artifact_control_outcome_fields(
            status=status,
            reason=artifact_policy_denied_reason(access, action=action),
        ),
    }


def build_artifact_control_unavailable_result(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
    status: str,
    reason: str,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "database": str(database_path),
        **serialize_artifact_control_outcome_fields(
            status=status,
            reason=reason,
        ),
    }


def build_artifact_control_success_result(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
    status: str,
    access: ArtifactAccessContext,
    lifecycle: dict[str, object],
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "database": str(database_path),
        **serialize_artifact_control_success_outcome_fields(
            access,
            status=status,
            lifecycle=lifecycle,
        ),
        **serialize_artifact_access_snapshot_attachment(access),
    }

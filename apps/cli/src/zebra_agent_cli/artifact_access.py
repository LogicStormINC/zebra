from __future__ import annotations

from pathlib import Path

from agent_security import ArtifactAccessProjection, serialize_artifact_access_projection

ArtifactAccessContext = ArtifactAccessProjection


def serialize_artifact_access(access: ArtifactAccessContext) -> dict[str, object]:
    return serialize_artifact_access_projection(access)


def artifact_policy_denied_reason(
    access: ArtifactAccessContext,
    *,
    action: str,
) -> str:
    return f"artifact_{action}_requires_{access.required_policy_profile}_policy"


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
        "status": status,
        "reason": reason,
        "access": serialize_artifact_access(access),
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
        "status": status,
        "reason": artifact_policy_denied_reason(access, action=action),
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
        "status": status,
        "reason": reason,
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
        "status": status,
        "access": serialize_artifact_access(access),
        "access_class": access.access_class,
        "required_policy_profile": access.required_policy_profile,
        "lifecycle": lifecycle,
    }

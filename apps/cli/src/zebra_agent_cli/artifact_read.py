from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from agent_core.domain import ArtifactAccessDescriptor
from agent_core.domain.artifact_payloads import StoredArtifactPayload
from agent_core.domain.identifiers import SessionId
from agent_security import (
    PolicyProfile,
    build_artifact_access_projection,
    policy_rank,
)
from agent_storage import (
    SessionArtifact,
    SQLiteArtifactPayloadStore,
    SQLiteArtifactStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    payload_for_artifact_uri,
    serialize_artifact_lifecycle,
    serialize_artifact_retrieval,
    serialize_session_artifact_projection,
)

from zebra_agent_cli.artifact_access import (
    ArtifactAccessContext,
    build_artifact_control_denied_result,
    build_artifact_control_success_result,
    build_artifact_control_unavailable_result,
    build_artifact_policy_denied_result,
    build_artifact_unavailable_result,
    serialize_artifact_access,
)


def list_artifacts(
    *,
    database_path: Path,
    session_id: str,
) -> dict[str, object]:
    session_key = SessionId(UUID(session_id))
    session = SQLiteProjectionStore(database_path).get_session(session_key)
    if session is None:
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "not_found",
        }
    artifacts = SQLiteArtifactStore(database_path).list_for_session(session_key)
    return {
        "session_id": session_id,
        "database": str(database_path),
        "artifacts": [
            _serialize_artifact_projection(database_path, session_id, artifact)
            for artifact in artifacts
        ],
    }


def read_artifact_detail(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
) -> dict[str, object]:
    resolved = _resolve_artifact(
        database_path=database_path,
        session_id=session_id,
        artifact_id=artifact_id,
    )
    if resolved is None:
        return {
            "session_id": session_id,
            "artifact_id": artifact_id,
            "database": str(database_path),
            "status": "not_found",
        }
    access = _artifact_access_context(
        database_path=database_path,
        session_id=session_id,
        artifact=resolved,
    )
    if not access.allowed:
        return build_artifact_policy_denied_result(
            database_path=database_path,
            session_id=session_id,
            artifact_id=artifact_id,
            status="artifact_access_denied",
            action="read",
            access=access,
        )
    lifecycle = _artifact_lifecycle(database_path, resolved.uri)
    projection = serialize_session_artifact_projection(
        resolved,
        lifecycle=lifecycle,
    )
    projection["access"] = serialize_artifact_access(access)
    return {
        "session_id": session_id,
        "artifact": projection,
        "database": str(database_path),
        "status": "ok",
    }


def read_artifact_content(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
) -> dict[str, object]:
    resolved = _resolve_artifact(
        database_path=database_path,
        session_id=session_id,
        artifact_id=artifact_id,
    )
    if resolved is None:
        return {
            "session_id": session_id,
            "artifact_id": artifact_id,
            "database": str(database_path),
            "status": "not_found",
        }
    access = _artifact_access_context(
        database_path=database_path,
        session_id=session_id,
        artifact=resolved,
    )
    if not access.allowed:
        return build_artifact_policy_denied_result(
            database_path=database_path,
            session_id=session_id,
            artifact_id=artifact_id,
            status="artifact_access_denied",
            action="read",
            access=access,
        )
    retrieval = serialize_artifact_retrieval(
        resolved.uri,
        lifecycle=_artifact_lifecycle(database_path, resolved.uri),
    )
    status = str(retrieval["status"])
    if status != "payload_available":
        return build_artifact_unavailable_result(
            database_path=database_path,
            session_id=session_id,
            artifact_id=artifact_id,
            reason=_artifact_unavailable_reason(status),
            access=access,
        )
    assert resolved.uri is not None
    payload = Path(urlparse(resolved.uri).path).read_bytes()
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "database": str(database_path),
        "status": "ok",
        "access": serialize_artifact_access(access),
        "encoding": "base64",
        "content_base64": base64.b64encode(payload).decode("ascii"),
        "size_bytes": len(payload),
    }


def prune_artifact(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
) -> dict[str, object]:
    resolved = _resolve_artifact(
        database_path=database_path,
        session_id=session_id,
        artifact_id=artifact_id,
    )
    if resolved is None:
        return {
            "session_id": session_id,
            "artifact_id": artifact_id,
            "database": str(database_path),
            "status": "not_found",
        }
    if resolved.uri is None:
        return _unavailable_artifact(
            database_path=database_path,
            session_id=session_id,
            artifact_id=artifact_id,
            reason="artifact_is_indexed_only",
        )
    parsed = urlparse(resolved.uri)
    if parsed.scheme != "file":
        return _unavailable_artifact(
            database_path=database_path,
            session_id=session_id,
            artifact_id=artifact_id,
            reason="artifact_uses_external_reference",
        )
    payload_store = SQLiteArtifactPayloadStore(database_path)
    payload = _payload_record_for_uri(payload_store, resolved.uri)
    if payload is None:
        return _unavailable_artifact(
            database_path=database_path,
            session_id=session_id,
            artifact_id=artifact_id,
            reason="artifact_payload_unmanaged",
        )
    access = _artifact_access_context(
        database_path=database_path,
        session_id=session_id,
        artifact=resolved,
        payload=payload,
    )
    if not access.allowed:
        return build_artifact_control_denied_result(
            database_path=database_path,
            session_id=session_id,
            artifact_id=artifact_id,
            status="artifact_prune_denied",
            action="prune",
            access=access,
        )
    already_pruned = payload.pruned_at is not None
    pruned = payload_store.prune_payload(payload.artifact_id)
    assert pruned is not None
    return build_artifact_control_success_result(
        database_path=database_path,
        session_id=session_id,
        artifact_id=artifact_id,
        status="already_pruned" if already_pruned else "pruned",
        access=access,
        lifecycle=_lifecycle_body(pruned),
    )


def _artifact_access_context(
    *,
    database_path: Path,
    session_id: str,
    artifact: SessionArtifact,
    payload: StoredArtifactPayload | None = None,
) -> ArtifactAccessContext:
    resolved_payload = payload or _payload_record_for_uri(
        SQLiteArtifactPayloadStore(database_path),
        artifact.uri,
    )
    return build_artifact_access_projection(
        ArtifactAccessDescriptor(
            kind=artifact.kind,
            mime_type=resolved_payload.mime_type if resolved_payload is not None else None,
            uri=artifact.uri,
            preview_redacted=artifact.preview_state["redacted"],
            preview_truncated=artifact.preview_state["truncated"],
        ),
        session_policy_profile=_session_policy_profile(database_path, session_id),
    )


def _serialize_artifact_projection(
    database_path: Path,
    session_id: str,
    artifact: SessionArtifact,
) -> dict[str, object]:
    lifecycle = _artifact_lifecycle(database_path, artifact.uri)
    projection = serialize_session_artifact_projection(
        artifact,
        lifecycle=lifecycle,
    )
    projection["access"] = serialize_artifact_access(
        _artifact_access_context(
            database_path=database_path,
            session_id=session_id,
            artifact=artifact,
        )
    )
    return projection


def _resolve_artifact(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
) -> SessionArtifact | None:
    session_key = SessionId(UUID(session_id))
    session = SQLiteProjectionStore(database_path).get_session(session_key)
    if session is None:
        return None
    artifacts = SQLiteArtifactStore(database_path).list_for_session(session_key)
    for artifact in artifacts:
        if artifact.artifact_id == artifact_id:
            return artifact
    return None


def _artifact_lifecycle(database_path: Path, uri: str | None) -> dict[str, object] | None:
    payload = payload_for_artifact_uri(SQLiteArtifactPayloadStore(database_path), uri)
    return serialize_artifact_lifecycle(payload)


def _artifact_unavailable_reason(status: str) -> str:
    mapping = {
        "indexed_only": "artifact_is_indexed_only",
        "external_reference": "artifact_uses_external_reference",
        "payload_missing": "artifact_payload_missing",
        "payload_pruned": "artifact_payload_pruned",
    }
    return mapping[status]


def _unavailable_artifact(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
    reason: str,
) -> dict[str, object]:
    return build_artifact_control_unavailable_result(
        database_path=database_path,
        session_id=session_id,
        artifact_id=artifact_id,
        status="artifact_prune_unavailable",
        reason=reason,
    )


def _payload_record_for_uri(
    payload_store: SQLiteArtifactPayloadStore,
    uri: str | None,
) -> StoredArtifactPayload | None:
    return payload_for_artifact_uri(payload_store, uri)


def _session_policy_profile(database_path: Path, session_id: str) -> str:
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(
        SessionId(UUID(session_id))
    )
    if workspace is None or workspace.policy_profile is None:
        return PolicyProfile.WORKSPACE_WRITE.value
    return workspace.policy_profile


def _policy_satisfies_requirement(
    session_policy_profile: str,
    required_policy_profile: str,
) -> bool:
    return policy_rank(session_policy_profile) >= policy_rank(required_policy_profile)


def _lifecycle_body(payload: StoredArtifactPayload) -> dict[str, object]:
    retained_until = payload.retained_until
    pruned_at = payload.pruned_at
    return {
        "status": payload.lifecycle_status.value,
        "retained_until": retained_until.isoformat() if retained_until is not None else None,
        "pruned_at": pruned_at.isoformat() if pruned_at is not None else None,
        "expired": False,
    }

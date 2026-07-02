from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from agent_core.domain.artifact_payloads import StoredArtifactPayload
from agent_core.domain.identifiers import SessionId
from agent_security import (
    build_session_artifact_access_projection,
    policy_rank,
    serialize_artifact_access_snapshot_attachment,
)
from agent_storage import (
    SessionArtifact,
    SQLiteArtifactPayloadStore,
    artifact_content_unavailable_reason,
    lifecycle_for_artifact_uri,
    resolve_payload_for_artifact_uri,
    resolve_session_artifact,
    serialize_artifact_retrieval,
    serialize_session_artifact_projection,
    session_policy_profile_for_session,
)

from zebra_agent_cli.artifact_access import (
    ArtifactAccessContext,
    build_artifact_control_denied_result,
    build_artifact_control_success_result,
    build_artifact_control_unavailable_result,
    build_artifact_policy_denied_result,
    build_artifact_unavailable_result,
)


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
    return {
        "session_id": session_id,
        "artifact": {
            **projection,
            **serialize_artifact_access_snapshot_attachment(access),
        },
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
    unavailable_reason = artifact_content_unavailable_reason(status)
    if unavailable_reason is not None:
        return build_artifact_unavailable_result(
            database_path=database_path,
            session_id=session_id,
            artifact_id=artifact_id,
            reason=unavailable_reason,
            access=access,
        )
    assert resolved.uri is not None
    payload = Path(urlparse(resolved.uri).path).read_bytes()
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "database": str(database_path),
        "status": "ok",
        **serialize_artifact_access_snapshot_attachment(access),
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
    payload = _payload_record_for_uri(database_path, resolved.uri)
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
        database_path,
        artifact.uri,
    )
    return build_session_artifact_access_projection(
        kind=artifact.kind,
        mime_type=resolved_payload.mime_type if resolved_payload is not None else None,
        uri=artifact.uri,
        preview_redacted=artifact.preview_state["redacted"],
        preview_truncated=artifact.preview_state["truncated"],
        session_policy_profile=_session_policy_profile(database_path, session_id),
    )


def _resolve_artifact(
    *,
    database_path: Path,
    session_id: str,
    artifact_id: str,
) -> SessionArtifact | None:
    resolution = resolve_session_artifact(
        database_path,
        SessionId(UUID(session_id)),
        artifact_id,
    )
    return resolution.artifact


def _artifact_lifecycle(database_path: Path, uri: str | None) -> dict[str, object] | None:
    return lifecycle_for_artifact_uri(SQLiteArtifactPayloadStore(database_path), uri)


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
    database_path: Path,
    uri: str | None,
) -> StoredArtifactPayload | None:
    return resolve_payload_for_artifact_uri(database_path, uri)


def _session_policy_profile(database_path: Path, session_id: str) -> str:
    return session_policy_profile_for_session(
        database_path,
        SessionId(UUID(session_id)),
    )


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

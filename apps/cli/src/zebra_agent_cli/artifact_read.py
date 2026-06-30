from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SessionArtifact, SQLiteArtifactStore, SQLiteProjectionStore


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
    retrieval = _artifact_retrieval(resolved.uri)
    return {
        "session_id": session_id,
        "artifact": {
            "artifact_id": resolved.artifact_id,
            "sequence": resolved.sequence,
            "source": resolved.source,
            "kind": resolved.kind,
            "label": resolved.label,
            "uri": resolved.uri,
            "preview": resolved.preview,
            "metadata": resolved.metadata,
            "retrieval": retrieval,
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
    retrieval = _artifact_retrieval(resolved.uri)
    status = str(retrieval["status"])
    if status != "payload_available":
        return {
            "session_id": session_id,
            "artifact_id": artifact_id,
            "database": str(database_path),
            "status": "artifact_unavailable",
            "reason": _artifact_unavailable_reason(status),
        }
    assert resolved.uri is not None
    payload = Path(urlparse(resolved.uri).path).read_bytes()
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "database": str(database_path),
        "status": "ok",
        "encoding": "base64",
        "content_base64": base64.b64encode(payload).decode("ascii"),
        "size_bytes": len(payload),
    }


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


def _artifact_retrieval(uri: str | None) -> dict[str, object]:
    if uri is None:
        return {"status": "indexed_only", "retrievable": False, "uri": None}
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return {"status": "external_reference", "retrievable": False, "uri": uri}
    payload_path = Path(parsed.path)
    available = payload_path.is_file()
    return {
        "status": "payload_available" if available else "payload_missing",
        "retrievable": available,
        "uri": uri,
    }


def _artifact_unavailable_reason(status: str) -> str:
    mapping = {
        "indexed_only": "artifact_is_indexed_only",
        "external_reference": "artifact_uses_external_reference",
        "payload_missing": "artifact_payload_missing",
    }
    return mapping[status]

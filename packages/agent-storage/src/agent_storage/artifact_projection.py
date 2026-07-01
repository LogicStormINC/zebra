from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from agent_core.domain.artifact_payloads import StoredArtifactPayload
from agent_core.domain.identifiers import ArtifactId

from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore
from agent_storage.artifacts import SessionArtifact


def payload_for_artifact_uri(
    payload_store: SQLiteArtifactPayloadStore,
    uri: str | None,
) -> StoredArtifactPayload | None:
    if uri is None:
        return None
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    try:
        artifact_id = ArtifactId(UUID(Path(parsed.path).parent.name))
    except ValueError:
        return None
    return payload_store.get_payload(artifact_id)


def serialize_artifact_lifecycle(
    payload: StoredArtifactPayload | None,
    *,
    now: datetime | None = None,
) -> dict[str, object] | None:
    if payload is None:
        return None
    retained_until = payload.retained_until
    effective_now = (now or datetime.now(UTC)).astimezone(UTC)
    return {
        "status": payload.lifecycle_status.value,
        "retained_until": retained_until.isoformat() if retained_until is not None else None,
        "pruned_at": payload.pruned_at.isoformat() if payload.pruned_at is not None else None,
        "expired": (
            payload.lifecycle_status.value == "active"
            and retained_until is not None
            and retained_until <= effective_now
        ),
    }


def serialize_artifact_retrieval(
    uri: str | None,
    *,
    lifecycle: dict[str, object] | None = None,
) -> dict[str, object]:
    if uri is None:
        return {
            "status": "indexed_only",
            "retrievable": False,
            "uri": None,
        }
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return {
            "status": "external_reference",
            "retrievable": False,
            "uri": uri,
        }
    if lifecycle is not None and lifecycle["status"] == "pruned":
        return {
            "status": "payload_pruned",
            "retrievable": False,
            "uri": uri,
        }
    payload_path = Path(parsed.path)
    available = payload_path.is_file()
    return {
        "status": "payload_available" if available else "payload_missing",
        "retrievable": available,
        "uri": uri,
    }


def serialize_session_artifact_projection(
    artifact: SessionArtifact,
    *,
    lifecycle: dict[str, object] | None = None,
    retrieval: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "artifact_id": artifact.artifact_id,
        "sequence": artifact.sequence,
        "source": artifact.source,
        "kind": artifact.kind,
        "label": artifact.label,
        "uri": artifact.uri,
        "preview": artifact.preview,
        "preview_state": artifact.preview_state,
        "metadata": artifact.metadata,
        "retrieval": retrieval or serialize_artifact_retrieval(
            artifact.uri,
            lifecycle=lifecycle,
        ),
        "lifecycle": lifecycle,
    }

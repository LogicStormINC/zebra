from datetime import UTC, datetime
from urllib.parse import urlparse

from agent_core.domain.identifiers import SessionId
from agent_core.ports import (
    ArtifactPayloadReadInspection,
    ArtifactPayloadReadPort,
    ArtifactPayloadReadStatus,
    SessionArtifact,
)
from agent_storage import ControlPlaneStores


def payload_reader(stores: ControlPlaneStores) -> ArtifactPayloadReadPort:
    return stores.artifact_payload_reader


def inspect_artifact_payload(
    stores: ControlPlaneStores,
    artifact: SessionArtifact,
) -> ArtifactPayloadReadInspection | None:
    if artifact.uri is None:
        return None
    inspection = payload_reader(stores).inspect_payload(artifact.session_id, artifact.uri)
    if inspection is None or inspection.bound_event_sequence is None:
        return inspection
    if (
        inspection.bound_event_sequence != artifact.sequence
        or inspection.bound_event_id != artifact.source_event_id
    ):
        return inspection.model_copy(update={"status": ArtifactPayloadReadStatus.UNAVAILABLE})
    return inspection


def describe_artifact_payload(
    stores: ControlPlaneStores,
    session_id: SessionId,
    uri: str | None,
) -> ArtifactPayloadReadInspection | None:
    if uri is None:
        return None
    return payload_reader(stores).describe_payload(session_id, uri)


def serialize_read_lifecycle(
    inspection: ArtifactPayloadReadInspection | None,
    *,
    now: datetime | None = None,
) -> dict[str, object] | None:
    if inspection is None:
        return None
    retained_until = inspection.retained_until
    effective_now = (now or datetime.now(UTC)).astimezone(UTC)
    return {
        "status": inspection.lifecycle_status,
        "retained_until": retained_until.isoformat() if retained_until is not None else None,
        "pruned_at": inspection.pruned_at.isoformat() if inspection.pruned_at is not None else None,
        "expired": (
            inspection.lifecycle_status == "active"
            and retained_until is not None
            and retained_until <= effective_now
        ),
    }


def serialize_read_retrieval(
    uri: str | None,
    inspection: ArtifactPayloadReadInspection | None,
) -> dict[str, object]:
    if uri is None:
        return {"status": "indexed_only", "retrievable": False, "uri": None}
    if urlparse(uri).scheme not in {"artifact", "file"}:
        return {"status": "external_reference", "retrievable": False, "uri": uri}
    status = inspection.status if inspection is not None else ArtifactPayloadReadStatus.MISSING
    return {
        "status": status.value,
        "retrievable": status is ArtifactPayloadReadStatus.AVAILABLE,
        "uri": uri,
    }

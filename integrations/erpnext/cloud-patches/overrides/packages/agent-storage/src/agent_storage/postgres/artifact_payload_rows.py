"""Row conversion for authoritative cloud Artifact payload metadata."""

from typing import Any

from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectReceipt,
)
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadLifecycleStatus,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactEventBinding,
    ArtifactReserveRequest,
)
from agent_core.domain.identifiers import ArtifactId, EventId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.http_input_attachments import HttpInputAuthority


def artifact_payload_from_row(row: dict[str, Any]) -> CloudArtifactPayloadRecord:
    kind = row['authority_kind']
    fence = tuple(row[k] for k in ('reservation_epoch', 'reservation_fencing_token', 'reservation_owner_instance_id'))
    if kind == 'worker':
        LeaseFence(control_plane_epoch=fence[0], fencing_token=fence[1], owner_instance_id=fence[2])
        if row['http_input_authority'] is not None:
            raise ValueError('Worker Artifact cannot carry HTTP input proof')
        input_authority = None
    elif kind == 'http_input' and fence == (None, None, None):
        input_authority = HttpInputAuthority.model_validate(row['http_input_authority'])
    else:
        raise ValueError('Artifact authority lane is malformed')
    namespace = row["deployment_namespace"]
    artifact_id = ArtifactId(row["artifact_id"])
    reservation = ArtifactReserveRequest(
        artifact_id=artifact_id,
        session_id=SessionId(row["session_id"]),
        intended_event_sequence=row["intended_event_sequence"],
        kind=row["kind"],
        mime_type=row["mime_type"],
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        idempotency_key=row["idempotency_key"],
        file_name=row["file_name"],
        retained_until=row["retained_until"],
        created_at=row["request_created_at"],
    )
    receipt = _object_receipt(row, namespace, artifact_id, reservation)
    binding = _event_binding(row, reservation)
    return CloudArtifactPayloadRecord(
        deployment_namespace=namespace,
        reservation=reservation,
        authority_kind=kind, input_authority=input_authority,
        lifecycle_status=CloudArtifactPayloadLifecycleStatus(row["lifecycle_status"]),
        lifecycle_revision=row["lifecycle_revision"],
        event_binding=binding,
        object_receipt=receipt,
        finalized_at=row["finalized_at"],
        compensated_at=row["compensated_at"],
        pruning_at=row["pruning_at"],
        pruned_at=row["pruned_at"],
    )


def _object_receipt(
    row: dict[str, Any],
    namespace: str,
    artifact_id: ArtifactId,
    reservation: ArtifactReserveRequest,
) -> ArtifactObjectReceipt | None:
    if row["object_version"] is None:
        return None
    return ArtifactObjectReceipt(
        expectation=ArtifactObjectExpectation(
            deployment_namespace=namespace,
            artifact_id=artifact_id,
            sha256=reservation.sha256,
            size_bytes=reservation.size_bytes,
        ),
        object_version=row["object_version"],
        verified_at=row["object_verified_at"],
    )


def _event_binding(
    row: dict[str, Any],
    reservation: ArtifactReserveRequest,
) -> ArtifactEventBinding | None:
    if row["event_id"] is None:
        return None
    return ArtifactEventBinding(
        session_id=reservation.session_id,
        event_id=EventId(row["event_id"]),
        sequence=row["event_sequence"],
        artifact_uri=row["artifact_uri"],
    )

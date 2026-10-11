"""Bounded exact coverage reservations in one fenced native transaction."""

from hashlib import sha256
from typing import Any

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadConflictError,
    CloudArtifactPayloadLifecycleStatus,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactReserveRequest,
    canonical_artifact_reserve_hash,
)
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.identifiers import ArtifactId
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from psycopg.types.json import Jsonb

from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.artifact_payload_transaction_support import (
    assert_stream_revision,
    hash_text,
)
from agent_storage.postgres.leases import assert_current_lease_fence


def reserve_batch(
    connection: Any, deployment: str, binding: CoverageRunBinding,
    payloads: tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...],
    authority: WorkerMutationAuthority,
) -> tuple[CloudArtifactPayloadRecord, ...]:
    assert_current_lease_fence(connection, deployment, binding.session_id, authority.lease_fence)
    identifiers = [identifier for identifier, _ in payloads]
    rows = connection.execute(
        """SELECT * FROM artifact_payload_metadata WHERE deployment_namespace=%s
           AND session_id=%s AND artifact_id=ANY(%s) ORDER BY artifact_id FOR UPDATE""",
        (deployment, binding.session_id, identifiers),
    ).fetchall()
    records = {row["artifact_id"]: artifact_payload_from_row(row) for row in rows}
    digest = coverage_digest(binding.model_dump(mode="json"))
    pending = []
    for identifier, payload in payloads:
        reservation_key = f"coverage:{digest}:{identifier}"
        record = records.get(identifier)
        if record is not None:
            reservation = record.reservation
            if reservation.idempotency_key != reservation_key:
                raise ValueError("coverage Artifact belongs to a different run or binding")
            if (
                reservation.sha256 != sha256(payload.payload).hexdigest()
                or reservation.size_bytes != len(payload.payload)
                or reservation.kind != payload.kind
                or reservation.mime_type != payload.mime_type
                or reservation.file_name != payload.file_name
                or reservation.retained_until != payload.retained_until
            ):
                raise ValueError("coverage immutable publication conflicts")
            if record.lifecycle_status not in {
                CloudArtifactPayloadLifecycleStatus.STAGED,
                CloudArtifactPayloadLifecycleStatus.FINALIZED,
            }:
                raise ValueError("coverage Artifact is pruned or compensated")
            continue
        request = ArtifactReserveRequest(
            artifact_id=identifier, session_id=binding.session_id,
            intended_event_sequence=authority.expected_stream_revision + 1,
            kind=payload.kind, mime_type=payload.mime_type,
            sha256=sha256(payload.payload).hexdigest(), size_bytes=len(payload.payload),
            idempotency_key=reservation_key, file_name=payload.file_name,
            retained_until=payload.retained_until, created_at=payload.created_at,
        )
        pending.append({
            **request.model_dump(mode="json"),
            "idempotency_key_hash": hash_text(reservation_key),
            "request_hash": canonical_artifact_reserve_hash(deployment, request),
        })
    if pending:
        assert_stream_revision(connection, deployment, binding.session_id,
                               authority.expected_stream_revision)
        rows = connection.execute(
            """INSERT INTO artifact_payload_metadata (
                deployment_namespace,artifact_id,session_id,intended_event_sequence,
                expected_stream_revision,kind,mime_type,sha256,size_bytes,idempotency_key,
                idempotency_key_hash,request_hash,file_name,retained_until,
                reservation_epoch,reservation_fencing_token,reservation_owner_instance_id,
                lifecycle_status,lifecycle_revision,request_created_at
            ) SELECT %s,r.artifact_id,%s,r.intended_event_sequence,%s,r.kind,r.mime_type,
                r.sha256,r.size_bytes,r.idempotency_key,r.idempotency_key_hash,r.request_hash,
                r.file_name,r.retained_until,%s,%s,%s,'staged',0,r.created_at
              FROM jsonb_to_recordset(%s) AS r(
                artifact_id uuid,intended_event_sequence bigint,kind text,mime_type text,
                sha256 text,size_bytes bigint,idempotency_key text,idempotency_key_hash text,
                request_hash text,file_name text,retained_until timestamptz,created_at timestamptz
              ) ORDER BY r.artifact_id ON CONFLICT DO NOTHING RETURNING *""",
            (deployment, binding.session_id, authority.expected_stream_revision,
             authority.lease_fence.control_plane_epoch, authority.lease_fence.fencing_token,
             authority.lease_fence.owner_instance_id, Jsonb(pending)),
        ).fetchall()
        if len(rows) != len(pending):
            # Missing rows cannot be locked. A concurrent exact reservation may
            # win after our SELECT; roll back the whole delta and retry under a
            # fresh fence/snapshot, where immutable identity is checked again.
            raise CloudArtifactPayloadConflictError("coverage reservation batch raced")
        records.update({row["artifact_id"]: artifact_payload_from_row(row) for row in rows})
    return tuple(records[identifier] for identifier in identifiers)

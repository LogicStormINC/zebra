"""Set-based exact receipt settlement; no object I/O or per-object authority reads."""

from typing import Any

from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadConflictError,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.cloud_artifact_requests import ArtifactRecordObjectRequest
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from psycopg.types.json import Jsonb

from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.artifact_payload_transaction_support import (
    assert_worker_boundary,
    hash_text,
    mutation_request_hash,
)
from agent_storage.postgres.leases import assert_current_lease_fence


def record_receipts(
    connection: Any, deployment: str, binding: CoverageRunBinding,
    records: tuple[CloudArtifactPayloadRecord, ...], receipts: tuple[ArtifactObjectReceipt, ...],
    authority: WorkerMutationAuthority,
) -> tuple[CloudArtifactPayloadRecord, ...]:
    if any(record.object_receipt is None for record in records):
        assert_worker_boundary(connection, deployment, binding.session_id, authority)
    else:
        assert_current_lease_fence(
            connection, deployment, binding.session_id, authority.lease_fence,
        )
    identifiers = [record.artifact_id for record in records]
    rows = connection.execute(
        """SELECT * FROM artifact_payload_metadata WHERE deployment_namespace=%s
           AND session_id=%s AND artifact_id=ANY(%s) ORDER BY artifact_id FOR UPDATE""",
        (deployment, binding.session_id, identifiers),
    ).fetchall()
    current = {row["artifact_id"]: artifact_payload_from_row(row) for row in rows}
    if len(current) != len(records):
        raise ValueError("coverage publication changed during object verification")
    for record in records:
        require_unchanged_publication(record, current[record.artifact_id])
    pending = []
    for record, receipt in zip(records, receipts, strict=True):
        if record.object_receipt is not None:
            if record.object_receipt != receipt:
                raise ValueError("coverage object receipt changed")
            continue
        expectation = receipt.expectation
        if (record.lifecycle_status != "staged" or record.lifecycle_revision != 0
                or expectation.deployment_namespace != deployment
                or expectation.artifact_id != record.artifact_id
                or expectation.sha256 != record.reservation.sha256
                or expectation.size_bytes != record.reservation.size_bytes):
            raise ValueError("coverage object receipt does not match reservation")
        request = ArtifactRecordObjectRequest(
            artifact_id=record.artifact_id, session_id=binding.session_id,
            expected_lifecycle_revision=0, idempotency_key=f"coverage-object:{record.artifact_id}",
            object_receipt=receipt,
        )
        pending.append({
            "artifact_id": str(record.artifact_id), "object_version": receipt.object_version,
            "verified_at": receipt.verified_at.isoformat(),
            "idempotency_hash": hash_text(request.idempotency_key),
            "request_hash": mutation_request_hash(deployment, "record_object", request),
        })
    if pending:
        replay = connection.execute(
            """SELECT 1 FROM artifact_payload_mutations WHERE deployment_namespace=%s
               AND artifact_id=ANY(%s) AND operation_kind='record_object' LIMIT 1""",
            (deployment, [record.artifact_id for record in records
                          if record.object_receipt is None]),
        ).fetchone()
        if replay is not None:
            raise ValueError("coverage staged receipt disagrees with mutation ledger")
        rows = connection.execute(
            """UPDATE artifact_payload_metadata m SET object_version=r.object_version,
               object_verified_at=r.verified_at,lifecycle_revision=1,updated_at=transaction_timestamp()
               FROM jsonb_to_recordset(%s) AS r(
                 artifact_id uuid,object_version text,verified_at timestamptz)
               WHERE m.deployment_namespace=%s AND m.session_id=%s AND m.artifact_id=r.artifact_id
                 AND m.lifecycle_status='staged' AND m.lifecycle_revision=0
                 AND m.object_version IS NULL
               RETURNING m.*""",
            (Jsonb(pending), deployment, binding.session_id),
        ).fetchall()
        if len(rows) != len(pending):
            raise ValueError("coverage receipt batch lost an exact lifecycle identity")
        connection.execute(
            """INSERT INTO artifact_payload_mutations (
               deployment_namespace,artifact_id,operation_kind,idempotency_key_hash,
               request_hash,resulting_revision)
               SELECT %s,r.artifact_id,'record_object',r.idempotency_hash,r.request_hash,1
               FROM jsonb_to_recordset(%s) AS r(
                 artifact_id uuid,idempotency_hash text,request_hash text)""",
            (deployment, Jsonb(pending)),
        )
        current.update({row["artifact_id"]: artifact_payload_from_row(row) for row in rows})
    return tuple(current[identifier] for identifier in identifiers)


def require_unchanged_publication(
    before: CloudArtifactPayloadRecord, current: CloudArtifactPayloadRecord,
) -> None:
    if current == before:
        return
    # A competing exact publisher may advance staged->recorded->finalized. The
    # caller must retry with a fresh authority/metadata snapshot, never accept
    # this changed snapshot. Changed bytes/identity or lifecycle reversal is not
    # a transport retry and stays a hard refusal.
    if (before.lifecycle_status == "staged"
            and current.lifecycle_status in {"staged", "finalized"}
            and current.lifecycle_revision > before.lifecycle_revision
            and current.reservation.model_copy(update={
                "intended_event_sequence": before.reservation.intended_event_sequence,
            }) == before.reservation
            and (before.object_receipt is None or current.object_receipt == before.object_receipt)):
        raise CloudArtifactPayloadConflictError(
            "coverage publication changed during object verification"
        )
    raise ValueError("coverage publication changed during object verification")

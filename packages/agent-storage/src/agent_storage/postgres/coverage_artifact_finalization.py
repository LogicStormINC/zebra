"""Set-based coverage materialization; caller owns the native run/stream locks."""

from datetime import UTC, datetime
from typing import Any

from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadRecord
from agent_core.domain.cloud_artifact_requests import (
    ArtifactEventBinding,
    ArtifactFinalizeRequest,
    canonical_artifact_reserve_hash,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from psycopg.types.json import Jsonb

from agent_storage.event_rows import SessionEventSequenceConflictError
from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.artifact_payload_transaction_support import (
    hash_text,
    mutation_request_hash,
)
from agent_storage.postgres.coverage_artifact_receipts import require_unchanged_publication
from agent_storage.postgres.coverage_transactions import validate_write


def finalize_batch(
    connection: Any, deployment: str, binding: CoverageRunBinding,
    records: tuple[CloudArtifactPayloadRecord, ...], authority: WorkerMutationAuthority,
    version: int,
) -> tuple[CloudArtifactPayloadRecord, ...]:
    identifiers = [record.artifact_id for record in records]
    rows = connection.execute(
        """SELECT * FROM artifact_payload_metadata WHERE deployment_namespace=%s
           AND session_id=%s AND artifact_id=ANY(%s) ORDER BY artifact_id FOR UPDATE""",
        (deployment, binding.session_id, identifiers),
    ).fetchall()
    current = {row["artifact_id"]: artifact_payload_from_row(row) for row in rows}
    if len(current) != len(records):
        raise ValueError("coverage finalization lost an exact lifecycle identity")
    for record in records:
        require_unchanged_publication(record, current[record.artifact_id])
        if (record.reservation.retained_until is not None
                and record.reservation.retained_until <= datetime.now(UTC)):
            raise ValueError("coverage Artifact retention has expired")
        if record.lifecycle_status not in {"staged", "finalized"}:
            raise ValueError("coverage Artifact changed lifecycle during publication")
    pending = [current[key] for key in identifiers if current[key].lifecycle_status == "staged"]
    if not pending:
        return tuple(current[key] for key in identifiers)
    if any(row.lifecycle_revision != 1 or row.object_receipt is None for row in pending):
        raise ValueError("coverage finalization requires exact recorded receipts")
    replay = connection.execute(
        """SELECT 1 FROM artifact_payload_mutations WHERE deployment_namespace=%s
           AND artifact_id=ANY(%s) AND operation_kind='finalize' LIMIT 1""",
        (deployment, [record.artifact_id for record in pending]),
    ).fetchone()
    if replay is not None:
        raise ValueError("coverage staged finalization disagrees with mutation ledger")
    now, _, _ = validate_write(connection, deployment, binding, authority.lease_fence)
    events, changes = [], []
    for offset, record in enumerate(pending, start=1):
        target = record.reservation.model_copy(update={"intended_event_sequence": version + offset})
        reservation_hash = canonical_artifact_reserve_hash(deployment, target)
        event = SessionEvent.create(
            session_id=binding.session_id, sequence=version + offset,
            event_type=EventType.COVERAGE_ARTIFACT_MATERIALIZED, actor=EventActor.SYSTEM,
            created_at=now, payload={
                "namespace": binding.namespace, "run_id": binding.run_id,
                "fence": authority.lease_fence.model_dump(mode="json"),
                "metadata": {"artifact_uri": record.uri},
                "previous_reservation": canonical_artifact_reserve_hash(
                    deployment, record.reservation),
                "reservation": reservation_hash, "sha256": record.reservation.sha256,
            },
        )
        assert record.object_receipt is not None
        request = ArtifactFinalizeRequest(
            artifact_id=record.artifact_id, session_id=binding.session_id,
            expected_lifecycle_revision=1,
            idempotency_key=f"coverage-finalize:{record.artifact_id}",
            object_receipt=record.object_receipt, finalized_at=event.created_at,
            event_binding=ArtifactEventBinding(
                session_id=binding.session_id, event_id=event.event_id,
                sequence=event.sequence, artifact_uri=record.uri,
            ),
        )
        events.append(event.model_dump(mode="json"))
        changes.append({
            "artifact_id": str(record.artifact_id), "sequence": event.sequence,
            "previous_version": event.sequence - 1, "reserve_hash": reservation_hash,
            "event_id": str(event.event_id), "uri": record.uri,
            "idempotency_hash": hash_text(request.idempotency_key),
            "request_hash": mutation_request_hash(deployment, "finalize", request),
        })
    advanced = connection.execute(
        """UPDATE session_streams SET current_version=%s
           WHERE deployment_namespace=%s AND session_id=%s AND current_version=%s
           RETURNING current_version""",
        (version + len(events), deployment, binding.session_id, version),
    ).fetchone()
    if advanced is None:
        raise SessionEventSequenceConflictError("session event sequence already taken")
    # Each object retains its own canonical Event. Only transport/commit is batched;
    # coverage materializations never admit commands and therefore create no wake.
    connection.execute(
        """INSERT INTO session_events (
           deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,created_at,
           causation_id,correlation_id,idempotency_key,policy_version,model_profile)
           SELECT %s,r.event_id,r.session_id,r.sequence,r.event_type,r.payload,r.actor,r.created_at,
             r.causation_id,r.correlation_id,r.idempotency_key,r.policy_version,r.model_profile
           FROM jsonb_to_recordset(%s) AS r(
             event_id uuid,session_id uuid,sequence bigint,event_type text,payload jsonb,actor text,
             created_at timestamptz,causation_id uuid,correlation_id uuid,idempotency_key text,
             policy_version text,model_profile text) ORDER BY r.sequence""",
        (deployment, Jsonb(events)),
    )
    updated = connection.execute(
        """UPDATE artifact_payload_metadata m SET intended_event_sequence=r.sequence,
           expected_stream_revision=r.previous_version,request_hash=r.reserve_hash,
           lifecycle_status='finalized',lifecycle_revision=2,event_id=r.event_id,
           event_sequence=r.sequence,artifact_uri=r.uri,finalized_at=transaction_timestamp(),
           updated_at=transaction_timestamp()
           FROM jsonb_to_recordset(%s) AS r(
             artifact_id uuid,sequence bigint,previous_version bigint,reserve_hash text,
             event_id uuid,uri text)
           WHERE m.deployment_namespace=%s AND m.session_id=%s AND m.artifact_id=r.artifact_id
             AND m.lifecycle_status='staged' AND m.lifecycle_revision=1
             AND m.object_version IS NOT NULL RETURNING m.*""",
        (Jsonb(changes), deployment, binding.session_id),
    ).fetchall()
    if len(updated) != len(pending):
        raise ValueError("coverage finalization lost an exact lifecycle identity")
    connection.execute(
        """INSERT INTO artifact_payload_mutations (
           deployment_namespace,artifact_id,operation_kind,idempotency_key_hash,
           request_hash,resulting_revision)
           SELECT %s,r.artifact_id,'finalize',r.idempotency_hash,r.request_hash,2
           FROM jsonb_to_recordset(%s) AS r(
             artifact_id uuid,idempotency_hash text,request_hash text)""",
        (deployment, Jsonb(changes)),
    )
    current.update({row["artifact_id"]: artifact_payload_from_row(row) for row in updated})
    return tuple(current[key] for key in identifiers)

"""Original checkpoint proof under the caller's same-run and payload lifecycle locks."""

from datetime import datetime
from hashlib import sha256
from typing import Any, cast

from agent_core.domain.artifact_payloads import StoredArtifactPayload
from agent_core.domain.cloud_artifact_requests import canonical_artifact_reserve_hash
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import (
    MAX_MODEL_CHECKPOINT_BYTES,
    MODEL_CHECKPOINT_KIND,
    decode_model_checkpoint,
    model_checkpoint_id,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports.artifact_payload_store import VerifiedArtifactPayloadReaderPort

from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.coverage_artifacts import pinned_payload_row, read_verified_artifact
from agent_storage.postgres.coverage_proof_prefetch import materialized_sources
from agent_storage.postgres.coverage_transactions import validate_event_fence


def checkpoint_source(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    receipt: CoverageModelUsageReceipt,
    *,
    reserved_sequence: int,
    receipt_sequence: int | None = None,
    artifacts: Any = None,
    proof: list[tuple[Any, Any]] | None = None,
) -> Any:
    """Never treat finalized row metadata alone as canonical Event authority."""
    artifact_id = model_checkpoint_id(binding, receipt.reservation)
    ref = f"artifact://{artifact_id}"
    if receipt.checkpoint_ref != ref or receipt.checkpoint_digest is None:
        raise ValueError("strict usage requires the original checkpoint reference/digest")
    row = pinned_payload_row(artifacts, connection, deployment, artifact_id, binding.session_id)
    record = artifact_payload_from_row(row)
    reservation, event_binding = record.reservation, record.event_binding
    if (
        record.lifecycle_status.value != "finalized"
        or event_binding is None
        or record.lifecycle_revision != 2
        or not 0 < reservation.size_bytes <= MAX_MODEL_CHECKPOINT_BYTES
        or reservation.sha256 != receipt.checkpoint_digest
        or reservation.kind != MODEL_CHECKPOINT_KIND
        or reservation.mime_type != "application/json"
        or reservation.idempotency_key
        != (f"coverage:{coverage_digest(binding.model_dump(mode='json'))}:{artifact_id}")
    ):
        raise ValueError("original checkpoint lifecycle/binding conflicts")
    sources = materialized_sources(
        artifacts, connection, deployment, binding, ref, event_id=event_binding.event_id,
    )
    if len(sources) != 1:
        raise ValueError("original checkpoint canonical Event missing or conflicting")
    event = SessionEvent.model_validate(sources[0])
    payload = event.payload
    validate_event_fence(payload)
    previous = payload.get("previous_reservation")
    if (
        type(previous) is not str
        or len(previous) != 64
        or any(character not in "0123456789abcdef" for character in previous)
    ):
        raise ValueError("original checkpoint previous reservation requires a strict digest")
    if (
        event.event_type != EventType.COVERAGE_ARTIFACT_MATERIALIZED
        or event.actor.value != "system"
        or event.event_id != event_binding.event_id
        or event.session_id != binding.session_id
        or event.sequence != event_binding.sequence
        or event.sequence != reservation.intended_event_sequence
        or event_binding.artifact_uri != ref
        or event.sequence <= reserved_sequence
        or (receipt_sequence is not None and event.sequence >= receipt_sequence)
        or payload.get("namespace") != binding.namespace
        or payload.get("run_id") != binding.run_id
        or payload.get("metadata") != {"artifact_uri": ref}
        or payload.get("sha256") != receipt.checkpoint_digest
        or payload.get("reservation") != canonical_artifact_reserve_hash(deployment, reservation)
        or row["request_hash"] != payload.get("reservation")
        or row["expected_stream_revision"] != event.sequence - 1
        or set(payload)
        != {
            "namespace",
            "run_id",
            "fence",
            "metadata",
            "sha256",
            "reservation",
            "previous_reservation",
        }
    ):
        raise ValueError("original checkpoint canonical Event linkage conflicts")
    if proof is not None:
        proof.append((record, event))
    return record


def check_checkpoint_retention(connection: Any, deadlines: list[datetime]) -> datetime:
    # ponytail: locks pin lifecycle rows, not time. Keep only the earliest bound;
    # rereading objects remains O(n) until a retention-pinned proof root exists.
    now: datetime = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    if deadlines and now >= deadlines[0]:
        raise ValueError("original checkpoint retention expired before final authority")
    return now


def verify_model_checkpoint(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    receipt: CoverageModelUsageReceipt,
    artifacts: Any,
    *,
    reserved_sequence: int,
    receipt_sequence: int | None = None,
    retention_deadlines: list[datetime] | None = None,
    proof: list[tuple[Any, Any]] | None = None,
) -> bytes:
    deadlines = [] if retention_deadlines is None else retention_deadlines
    record = checkpoint_source(
        connection,
        deployment,
        binding,
        receipt,
        reserved_sequence=reserved_sequence,
        receipt_sequence=receipt_sequence,
        artifacts=artifacts,
        proof=proof,
    )
    ref, digest = record.uri, record.reservation.sha256
    # checkpoint_source already pins the finalized row and its canonical Event.
    # Compare that locked record with the fresh, pre/post-checked read result;
    # never fetch a second lifecycle snapshot solely for the same comparison.
    metadata, body = read_verified_artifact(artifacts, ref, digest, binding.session_id)
    if (
        metadata.kind != record.reservation.kind
        or metadata.mime_type != record.reservation.mime_type
        or metadata.size_bytes != record.reservation.size_bytes
        or metadata.retained_until != record.reservation.retained_until
    ):
        raise ValueError("original checkpoint reader disagrees with locked metadata")
    checkpoint = decode_model_checkpoint(body)
    if checkpoint.binding != binding:
        raise ValueError("original checkpoint belongs to another run")
    checkpoint.validate_receipt(receipt)
    deadline = record.reservation.retained_until
    if deadline is not None:
        deadlines[:] = [min(deadlines[0], deadline) if deadlines else deadline]
    check_checkpoint_retention(connection, deadlines)
    return body


class _CheckpointBodies:
    """One proof invocation's bounded immutable bytes, never cached authority."""

    def __init__(self, artifacts: Any) -> None:
        self._artifacts = artifacts
        self._bodies: dict[Any, tuple[Any, bytes]] = {}
        self._size = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._artifacts, name)

    def read_payload_verified_bounded(
        self, artifact_id: ArtifactId, *, session_id: SessionId, digest: str, max_bytes: int
    ) -> tuple[StoredArtifactPayload, bytes]:
        from agent_storage.postgres.coverage_artifacts import (
            MAX_COVERAGE_ARTIFACT_BYTES,
            _validate_metadata,
        )

        if type(max_bytes) is not int or not 0 <= max_bytes <= MAX_COVERAGE_ARTIFACT_BYTES:
            raise ValueError("invalid original checkpoint read bound")
        previous = self._bodies.get(artifact_id)
        if previous is None and isinstance(self._artifacts, VerifiedArtifactPayloadReaderPort):
            metadata, body = self._artifacts.read_payload_verified_bounded(
                artifact_id, session_id=session_id, digest=digest, max_bytes=max_bytes
            )
        else:
            metadata = _validate_metadata(
                self._artifacts.get_payload(artifact_id), artifact_id, session_id, digest
            )
            if metadata.size_bytes > max_bytes:
                raise ValueError("original checkpoint byte bound conflicts")
            if previous is not None:
                if previous[0] != metadata:
                    raise ValueError("cached original checkpoint metadata changed")
                body = previous[1]
            else:
                body = self._artifacts.read_payload_bytes_bounded(artifact_id, max_bytes=max_bytes)
            if self._artifacts.get_payload(artifact_id) != metadata:
                raise ValueError("original checkpoint metadata changed during read")
        _validate_metadata(metadata, artifact_id, session_id, digest)
        if len(body) != metadata.size_bytes or len(body) > max_bytes:
            raise ValueError("original checkpoint cache byte bound conflicts")
        if sha256(body).hexdigest() != digest:
            raise ValueError("original checkpoint bytes are corrupt")
        if previous is None:
            # ponytail: all verified proof bodies share this invocation's 32 MiB
            # budget; final proof uses a new reader. Overflow falls back to I/O.
            if self._size + len(body) <= MAX_COVERAGE_ARTIFACT_BYTES:
                self._bodies[artifact_id] = metadata, body
                self._size += len(body)
        return metadata, body

    def read_payload_bytes_bounded(self, artifact_id: Any, *, max_bytes: int) -> bytes:
        from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES

        metadata = self._artifacts.get_payload(artifact_id)
        if metadata is None or metadata.kind != MODEL_CHECKPOINT_KIND:
            return cast(
                bytes, self._artifacts.read_payload_bytes_bounded(artifact_id, max_bytes=max_bytes)
            )
        previous = self._bodies.get(artifact_id)
        if previous is not None:
            if previous[0] != metadata or len(previous[1]) > max_bytes:
                raise ValueError("cached original checkpoint metadata/byte bound changed")
            return previous[1]
        if self._size + metadata.size_bytes > MAX_COVERAGE_ARTIFACT_BYTES:
            raise ValueError("original checkpoint cache exceeds cumulative read bound")
        body = cast(
            bytes, self._artifacts.read_payload_bytes_bounded(artifact_id, max_bytes=max_bytes)
        )
        # The caller still validates digest, native source, receipt and retention every use.
        if self._artifacts.get_payload(artifact_id) != metadata:
            raise ValueError("original checkpoint metadata changed during read")
        if len(body) != metadata.size_bytes or len(body) > max_bytes:
            raise ValueError("original checkpoint cache byte bound conflicts")
        self._size += len(body)
        self._bodies[artifact_id] = metadata, body
        return body


def verify_settled_checkpoints(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    artifacts: Any,
    *,
    retention_deadlines: list[datetime] | None = None,
) -> None:
    deadlines = [] if retention_deadlines is None else retention_deadlines
    # ponytail: new calls require O(n) settled object reads (O(n^2) cumulative).
    # Batch indexes by the existing primary key; removing these lifecycle checks
    # requires a retention-pinned immutable proof root, not row hashes alone.
    cursor: str | None = None
    while True:
        rows = connection.execute(
            """SELECT reservation_key,receipt,reserved_sequence,receipt_sequence
               FROM coverage_model_calls WHERE deployment_namespace=%s AND namespace=%s
               AND run_id=%s AND receipt IS NOT NULL
               AND (%s::text IS NULL OR reservation_key>%s)
               ORDER BY reservation_key LIMIT 100""",
            (deployment, binding.namespace, binding.run_id, cursor, cursor),
        ).fetchall()
        if not rows:
            check_checkpoint_retention(connection, deadlines)
            return
        for row in rows:
            verify_model_checkpoint(
                connection,
                deployment,
                binding,
                CoverageModelUsageReceipt.model_validate(row["receipt"]),
                artifacts,
                reserved_sequence=row["reserved_sequence"],
                receipt_sequence=row["receipt_sequence"],
                retention_deadlines=deadlines,
            )
        cursor = rows[-1]["reservation_key"]

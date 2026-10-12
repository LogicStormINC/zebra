"""Recover immutable uploads and atomically bind a bounded batch of canonical Events."""
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectPutRequest,
    ArtifactObjectReceipt,
)
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadRecord
from agent_core.domain.cloud_artifact_requests import (
    canonical_artifact_reserve_hash,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.identifiers import ArtifactId
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort

from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.coverage_artifact_finalization import finalize_batch
from agent_storage.postgres.coverage_artifact_receipts import (
    record_receipts,
)
from agent_storage.postgres.coverage_artifact_reservations import reserve_batch
from agent_storage.postgres.coverage_transactions import (
    lock_run,
    validate_write,
    validated_binding,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.work_unit import postgres_transaction_work_unit


class PostgresCoverageArtifactPublisher:
    def __init__(
        self, dsn: str, *, deployment_namespace: str,
        metadata: PostgresCloudArtifactPayloadStore, objects: ArtifactObjectStorePort,
    ) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._metadata, self._objects = metadata, objects
        self._deployment = deployment_namespace

    def publish(
        self, binding: CoverageRunBinding, payload: ArtifactPayloadWrite, *,
        artifact_id: ArtifactId, authority: WorkerMutationAuthority,
        check_authority: Callable[[], None],
    ) -> CloudArtifactPayloadRecord:
        return self.publish_batch(
            binding, ((artifact_id, payload),), authority=authority,
            check_authority=check_authority,
        )[0]

    def publish_batch(
        self, binding: CoverageRunBinding,
        payloads: tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...], *,
        authority: WorkerMutationAuthority, check_authority: Callable[[], None],
    ) -> tuple[CloudArtifactPayloadRecord, ...]:
        binding = validated_binding(binding)
        payloads = self._prepare_publication(binding, payloads, authority)
        check_authority()
        with self._database.connect() as connection, postgres_transaction_work_unit(
            self._database, connection,
        ):
            records = reserve_batch(connection, self._deployment, binding, payloads, authority)
        receipts, _ = self._upload_verified(binding, records, payloads, check_authority)
        check_authority()
        with self._database.connect() as connection, postgres_transaction_work_unit(
            self._database, connection,
        ):
            row, version = lock_run(connection, self._deployment, binding, authority.lease_fence)
            result, _ = self._finalize_locked(
                connection, binding, records, receipts, authority, row, version,
            )
            check_authority()
            validate_write(connection, self._deployment, binding, authority.lease_fence)
            self._revalidate_finalized(connection, binding, result)
        return result

    def _prepare_publication(
        self, binding: CoverageRunBinding,
        payloads: tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...],
        authority: WorkerMutationAuthority,
    ) -> tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...]:
        if not isinstance(payloads, tuple) or not 1 <= len(payloads) <= 1000:
            raise ValueError("invalid coverage Artifact batch count")
        if any(not isinstance(identifier, UUID) for identifier, _ in payloads):
            raise ValueError("invalid coverage Artifact identity")
        payloads = tuple((ArtifactId(identifier), ArtifactPayloadWrite.model_validate(
            payload.model_dump(), strict=True,
        )) for identifier, payload in payloads)
        if len({identifier for identifier, _ in payloads}) != len(payloads):
            raise ValueError("duplicate coverage Artifact identity")
        if (authority.session_id != binding.session_id
                or authority.deployment_namespace != self._deployment
                or any(payload.session_id != binding.session_id for _, payload in payloads)):
            raise ValueError("coverage publication authority does not bind the Session")
        if sum(len(payload.payload) for _, payload in payloads) > 32 * 1024 * 1024:
            raise ValueError("coverage Artifact exceeds physical read bound")
        if any(payload.retained_until is not None and payload.retained_until <= datetime.now(UTC)
               for _, payload in payloads):
            raise ValueError("coverage Artifact retention has expired")
        return payloads

    def _upload_verified(
        self, binding: CoverageRunBinding, records: tuple[CloudArtifactPayloadRecord, ...],
        payloads: tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...],
        check_authority: Callable[[], None],
    ) -> tuple[tuple[ArtifactObjectReceipt, ...], tuple[bytes, ...]]:
        receipts, bodies = [], []
        # No connection/work unit survives object I/O. Interrupted uploads leave
        # only staged reservations; deterministic IDs recover exact bytes.
        for record, (_, payload) in zip(records, payloads, strict=True):
            expectation = ArtifactObjectExpectation(
                deployment_namespace=self._deployment, artifact_id=record.artifact_id,
                sha256=record.reservation.sha256, size_bytes=record.reservation.size_bytes,
            )
            receipt = record.object_receipt
            if receipt is None:
                check_authority()
                receipt = self._objects.put_if_absent(
                    ArtifactObjectPutRequest(expectation=expectation, payload=payload.payload)
                )
                check_authority()
            check_authority()
            body = self._objects.read_version_verified(expectation, receipt.object_version)
            check_authority()
            if body != payload.payload:
                raise ValueError("coverage object bytes changed")
            receipts.append(receipt)
            bodies.append(body)
        return tuple(receipts), tuple(bodies)

    def _finalize_locked(
        self, connection: Any, binding: CoverageRunBinding,
        records: tuple[CloudArtifactPayloadRecord, ...],
        receipts: tuple[ArtifactObjectReceipt, ...],
        authority: WorkerMutationAuthority, row: Any, version: int,
    ) -> tuple[tuple[CloudArtifactPayloadRecord, ...], int]:
        # This fresh read runs after lock waits, never from the upload's authority snapshot.
        validate_write(connection, self._deployment, binding, authority.lease_fence)
        pending = sum(record.lifecycle_status == "staged" for record in records)
        recorded = self._record_receipts(binding, records, receipts, authority)
        result = finalize_batch(
            connection, self._deployment, binding, recorded, authority, version,
        )
        return result, version + pending

    def _revalidate_finalized(
        self, connection: Any, binding: CoverageRunBinding,
        records: tuple[CloudArtifactPayloadRecord, ...],
    ) -> None:
        # A callback can use the borrowed connection: pins alone do not stop
        # same-transaction mutation. Recheck every exact returned record/Event.
        rows = connection.execute(
            """SELECT m.*,e.payload AS coverage_payload,e.sequence AS coverage_sequence
               FROM artifact_payload_metadata m LEFT JOIN session_events e
                 ON e.deployment_namespace=m.deployment_namespace AND e.session_id=m.session_id
                 AND e.event_id=m.event_id AND e.event_type='coverage_artifact_materialized'
               WHERE m.deployment_namespace=%s AND m.session_id=%s AND m.artifact_id=ANY(%s)""",
            (self._deployment, binding.session_id, [record.artifact_id for record in records]),
        ).fetchall()
        indexed = {row["artifact_id"]: row for row in rows}
        now = datetime.now(UTC)
        for record in records:
            row = indexed.get(record.artifact_id)
            payload = row["coverage_payload"] if row is not None else None
            if (row is None or artifact_payload_from_row(row) != record or payload is None
                    or payload.get("namespace") != binding.namespace
                    or payload.get("run_id") != binding.run_id
                    or payload.get("metadata", {}).get("artifact_uri") != record.uri
                    or payload.get("sha256") != record.reservation.sha256
                    or payload.get("reservation") != canonical_artifact_reserve_hash(
                        self._deployment, record.reservation)
                    or row["coverage_sequence"] != record.reservation.intended_event_sequence
                    or (record.reservation.retained_until is not None
                        and record.reservation.retained_until <= now)):
                raise ValueError("coverage Artifact batch changed before final commit")

    def _record_receipts(
        self, binding: CoverageRunBinding, records: tuple[CloudArtifactPayloadRecord, ...],
        receipts: tuple[ArtifactObjectReceipt, ...], authority: WorkerMutationAuthority,
    ) -> tuple[CloudArtifactPayloadRecord, ...]:
        with self._database.connect() as connection, postgres_transaction_work_unit(
            self._database, connection,
        ):
            return record_receipts(
                connection, self._deployment, binding, records, receipts, authority,
            )

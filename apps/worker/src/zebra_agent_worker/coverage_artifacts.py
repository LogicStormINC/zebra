"""Coverage-only cloud Artifact facade; staged uploads are never readable evidence."""

from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from agent_core.domain.artifact_payloads import (
    ArtifactPayloadInspection,
    ArtifactPayloadLifecycleStatus,
    ArtifactPayloadStatus,
    ArtifactPayloadWrite,
    StoredArtifactPayload,
)
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadLifecycleStatus,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.cloud_artifact_requests import ArtifactMetadataQuery
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher
from agent_storage.postgres.work_unit import postgres_transaction_work_unit, postgres_work_unit


class CloudCoverageArtifacts:
    def _execution_receipt_verifier(self, derive: Any) -> str | None:
        """Trusted facade qualifies the actual callback, never its declared name."""
        from agent_integrations.coverage_model_derivation import derive_semantic_observation

        from zebra_agent_worker.coverage_continuation import NATIVE_CONTINUATION_VERIFIER

        if type(self) is CloudCoverageArtifacts and derive is derive_semantic_observation:
            return NATIVE_CONTINUATION_VERIFIER
        return None

    def __init__(
        self,
        *,
        binding: CoverageRunBinding,
        deployment_namespace: str,
        metadata: PostgresCloudArtifactPayloadStore,
        objects: ArtifactObjectStorePort,
        publisher: PostgresCoverageArtifactPublisher,
        authority: Callable[[], WorkerMutationAuthority],
        check_authority: Callable[[], None],
        sync_events: Callable[[], None],
    ) -> None:
        self.binding, self.deployment = binding, deployment_namespace
        self.metadata, self.objects, self.publisher = metadata, objects, publisher
        self.authority, self.check_authority, self.sync_events = (
            authority,
            check_authority,
            sync_events,
        )
        self.check_local_authority: Callable[[], None] | None = None
        self.check_external_authority: Callable[[], None] | None = None
        self.reuse_verified_payloads = False
        self._verified_payloads: OrderedDict[
            ArtifactId, tuple[CloudArtifactPayloadRecord, bytes]
        ] = OrderedDict()
        self._verified_bytes = 0
        self._verified_payload_owner = self

    @contextmanager
    def _locked_proof_scope(
        self, connection: Any, deployment: str, binding: CoverageRunBinding, *,
        derive: Any = None, final_certification: bool = False,
    ) -> Iterator["CloudCoverageArtifacts"]:
        from agent_integrations.coverage_model_derivation import derive_semantic_observation

        from zebra_agent_worker.coverage_proof_reads import LockedCoverageProofReads

        if deployment != self.deployment or binding != self.binding:
            raise ValueError("locked Artifact proof scope conflicts")
        if final_certification and derive is not derive_semantic_observation:
            # Arbitrary callbacks may write metadata or release transaction pins.
            reuse = self.reuse_verified_payloads
            self.reuse_verified_payloads = False
            try:
                yield self
            finally:
                self.reuse_verified_payloads = reuse
            return
        # Pure native proof already owns a transaction. Nested authority/read
        # adapters borrow it rather than open/reset one socket for each getter.
        unit = (postgres_transaction_work_unit(self.metadata._database, connection)
                if getattr(connection, "info", None) is not None else nullcontext())
        with unit:
            self.check_authority()
            reader = LockedCoverageProofReads(
                self, connection, reuse_records=derive is derive_semantic_observation
            )
            if not final_certification and reader._reuse_records and self.reuse_verified_payloads:
                reader.reuse_verified_payloads = True
                reader._verified_payload_owner = self
            try:
                yield reader
                self.check_authority()  # Before the enclosing transaction can commit.
            finally:
                reader._proof_connection = None
                reader._proof_records.clear()
                reader._proof_rows.clear()
                reader._proof_events.clear()

    def _record(self, artifact_id: ArtifactId) -> CloudArtifactPayloadRecord | None:
        local, external = self.check_local_authority, self.check_external_authority
        if local is not None and external is not None:
            external()  # Host I/O finishes before starting the short database unit.
        else:
            self.check_authority()
        with postgres_work_unit(self.metadata._database) if local is not None else nullcontext():
            if local is not None:
                local()
            record = self.metadata.get_metadata(
                ArtifactMetadataQuery(
                    deployment_namespace=self.deployment,
                    session_id=self.binding.session_id,
                    artifact_id=artifact_id,
                )
            )
        if record is not None and (
            record.reservation.retained_until is not None
            and record.reservation.retained_until <= datetime.now(UTC)
        ):
            return None
        return record

    @contextmanager
    def read_payload_scope(
        self, artifact_ids: tuple[ArtifactId, ...],
    ) -> Iterator["CloudCoverageArtifacts"]:
        from agent_storage.postgres.work_unit import borrow_work_unit

        from zebra_agent_worker.coverage_prepared_reads import prepared_reads

        # Only this exact native composition may coalesce execution reads. Other
        # facades/callbacks keep per-getter authority and metadata checks.
        if (type(self) is not CloudCoverageArtifacts or borrow_work_unit(
                (self.metadata._database._dsn, self.deployment)) is not None):
            # Existing proof/custom callbacks keep public guarded reads under
            # their owner's locks; this is not an unlocked/coalesced read phase.
            yield self
            return
        with prepared_reads(self, artifact_ids) as reader:
            yield reader

    @staticmethod
    def _stored(record: CloudArtifactPayloadRecord) -> StoredArtifactPayload:
        request = record.reservation
        return StoredArtifactPayload(
            artifact_id=record.artifact_id,
            session_id=record.session_id,
            kind=request.kind,
            mime_type=request.mime_type,
            uri=record.uri,
            sha256=request.sha256,
            size_bytes=request.size_bytes,
            lifecycle_status=ArtifactPayloadLifecycleStatus.ACTIVE,
            retained_until=request.retained_until,
            created_at=request.created_at,
        )

    def get_payload(self, artifact_id: ArtifactId) -> StoredArtifactPayload | None:
        record = self._record(artifact_id)
        if (
            record is None
            or record.lifecycle_status != CloudArtifactPayloadLifecycleStatus.FINALIZED
        ):
            return None
        return self._stored(record)

    def inspect_payload(self, artifact_id: ArtifactId) -> ArtifactPayloadInspection | None:
        stored = self.get_payload(artifact_id)
        return (
            None
            if stored is None
            else ArtifactPayloadInspection(
                artifact_id=artifact_id,
                status=ArtifactPayloadStatus.AVAILABLE,
                payload=stored,
            )
        )

    def store_payload_immutable(
        self, payload: ArtifactPayloadWrite, *, artifact_id: ArtifactId
    ) -> StoredArtifactPayload:
        if payload.retained_until is not None and payload.retained_until <= datetime.now(UTC):
            raise ValueError("coverage Artifact retention has expired")
        self.sync_events()
        record = self.publisher.publish(
            self.binding,
            payload,
            artifact_id=artifact_id,
            authority=self.authority(),
            check_authority=self.check_authority,
        )
        self.sync_events()
        return self._stored(record)

    def store_payloads_immutable(
        self, payloads: tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...],
    ) -> tuple[StoredArtifactPayload, ...]:
        self.sync_events()
        records = self.publisher.publish_batch(
            self.binding, payloads, authority=self.authority(),
            check_authority=self.check_authority,
        )
        self.sync_events()
        return tuple(self._stored(record) for record in records)

    def store_payload(
        self, payload: ArtifactPayloadWrite, *, artifact_id: ArtifactId | None = None
    ) -> StoredArtifactPayload:
        if artifact_id is None:
            raise ValueError("coverage requires deterministic Artifact identity")
        return self.store_payload_immutable(payload, artifact_id=artifact_id)

    def read_payload_bytes_bounded(self, artifact_id: ArtifactId, *, max_bytes: int) -> bytes:
        if type(max_bytes) is not int or not 0 <= max_bytes <= 32 * 1024 * 1024:
            raise ValueError("invalid coverage Artifact read bound")
        record = self._record(artifact_id)
        return self._read_payload_bytes_for_record(artifact_id, record, max_bytes=max_bytes)

    def read_payload_verified_bounded(
        self, artifact_id: ArtifactId, *, session_id: SessionId, digest: str, max_bytes: int
    ) -> tuple[StoredArtifactPayload, bytes]:
        if type(max_bytes) is not int or not 0 <= max_bytes <= 32 * 1024 * 1024:
            raise ValueError("invalid coverage Artifact read bound")
        if session_id != self.binding.session_id:
            raise ValueError("coverage Artifact belongs to another Session")
        record = self._record(artifact_id)
        if (
            record is None
            or record.artifact_id != artifact_id
            or record.session_id != session_id
            or record.reservation.sha256 != digest
        ):
            raise ValueError("coverage Artifact identity or digest conflicts")
        body = self._read_payload_bytes_for_record(artifact_id, record, max_bytes=max_bytes)
        return self._stored(record), body

    def _read_payload_bytes_for_record(
        self, artifact_id: ArtifactId, record: CloudArtifactPayloadRecord | None, *, max_bytes: int
    ) -> bytes:
        # ponytail: internal callers have just obtained _record's fresh authority;
        # share that pre-read guard, never cache it across reads or callbacks.
        if (
            record is None
            or record.lifecycle_status != CloudArtifactPayloadLifecycleStatus.FINALIZED
            or record.object_receipt is None
            or record.reservation.size_bytes > max_bytes
        ):
            raise ValueError("coverage Artifact is unavailable or exceeds the read bound")
        receipt = record.object_receipt
        cache = self._verified_payload_owner
        previous = (
            cache._verified_payloads.get(artifact_id) if self.reuse_verified_payloads else None
        )
        data = previous[1] if previous is not None and previous[0] == record else (
            self.objects.read_version_verified(receipt.expectation, receipt.object_version)
        )
        if self._record(artifact_id) != record:
            raise ValueError("coverage Artifact changed while reading")
        if self.reuse_verified_payloads and len(data) <= 32 * 1024 * 1024:
            old = cache._verified_payloads.pop(artifact_id, None)
            cache._verified_bytes -= len(old[1]) if old is not None else 0
            while cache._verified_payloads and (
                len(cache._verified_payloads) >= 256
                or cache._verified_bytes + len(data) > 32 * 1024 * 1024
            ):
                _, (_, evicted) = cache._verified_payloads.popitem(last=False)
                cache._verified_bytes -= len(evicted)
            # Only incremental admission permits reuse across proof phases in a
            # callback. Independent certification constructs a fresh reader.
            cache._verified_payloads[artifact_id] = (deepcopy(record), data)
            cache._verified_bytes += len(data)
        return data

    def read_payload_bytes(self, artifact_id: ArtifactId) -> bytes:
        return self.read_payload_bytes_bounded(artifact_id, max_bytes=32 * 1024 * 1024)

    def prune_payload(
        self, artifact_id: ArtifactId, *, pruned_at: datetime | None = None
    ) -> StoredArtifactPayload | None:
        raise ValueError("coverage Workers cannot prune governed Artifacts")

    def sweep_expired_payloads(
        self, *, as_of: datetime | None = None
    ) -> list[StoredArtifactPayload]:
        raise ValueError("coverage Workers cannot sweep governed Artifacts")

"""Session-bound read-only Cloud evidence for the existing certificate gate."""

from datetime import UTC, datetime

from agent_core.domain.artifact_payloads import (
    ArtifactPayloadInspection,
    ArtifactPayloadLifecycleStatus,
    ArtifactPayloadStatus,
    ArtifactPayloadWrite,
    StoredArtifactPayload,
)
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_core.domain.cloud_artifact_requests import ArtifactMetadataQuery
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports import ArtifactPayloadObjectReadPort, CloudArtifactPayloadStorePort

from agent_storage.artifact_payload_reads import CloudArtifactPayloadReader
from agent_storage.postgres.coverage_recovery_preparation import remaining_recovery_time


class CloudCoverageArtifactReader:
    def __init__(
        self,
        metadata: CloudArtifactPayloadStorePort,
        objects: ArtifactPayloadObjectReadPort,
        *,
        deployment_namespace: str,
        session_id: SessionId,
        deadline_monotonic: float | None = None,
    ) -> None:
        self._metadata = metadata
        self._deployment = deployment_namespace
        self._session = session_id
        self._deadline = deadline_monotonic
        self._reader = CloudArtifactPayloadReader(
            metadata, objects, deployment_namespace=deployment_namespace
        )

    def get_payload(self, artifact_id: ArtifactId) -> StoredArtifactPayload | None:
        if self._deadline is not None:
            remaining_recovery_time(self._deadline)
        record = self._metadata.get_metadata(
            ArtifactMetadataQuery(
                deployment_namespace=self._deployment,
                session_id=self._session,
                artifact_id=artifact_id,
            )
        )
        if record is None:
            return None
        request = record.reservation
        if (
            record.session_id != self._session
            or record.artifact_id != artifact_id
            or record.lifecycle_status is not CloudArtifactPayloadLifecycleStatus.FINALIZED
            or record.deployment_namespace != self._deployment
            or (request.retained_until is not None and request.retained_until <= datetime.now(UTC))
        ):
            return None
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

    def inspect_payload(self, artifact_id: ArtifactId) -> ArtifactPayloadInspection | None:
        payload = self.get_payload(artifact_id)
        return (
            None
            if payload is None
            else ArtifactPayloadInspection(
                artifact_id=artifact_id,
                status=ArtifactPayloadStatus.AVAILABLE,
                payload=payload,
            )
        )

    def read_payload_bytes_bounded(self, artifact_id: ArtifactId, *, max_bytes: int) -> bytes:
        if type(max_bytes) is not int or not 0 <= max_bytes <= 32 * 1024 * 1024:
            raise ValueError("invalid coverage Artifact read bound")
        before = self.get_payload(artifact_id)
        if before is None or before.size_bytes > max_bytes:
            raise ValueError("coverage Artifact is unavailable or exceeds the read bound")
        if self._deadline is None:
            body = self._reader.read_payload_bytes(
                self._session, before.uri, max_bytes=max(1, max_bytes)
            )
        else:
            remaining_recovery_time(self._deadline)
            record = self._reader._get_record(self._session, artifact_id)
            if (
                record is None
                or record.lifecycle_status is not CloudArtifactPayloadLifecycleStatus.FINALIZED
                or record.object_receipt is None
                or self.get_payload(artifact_id) != before
            ):
                raise ValueError("coverage Artifact changed while reading")
            bounded_read = getattr(self._reader._objects, "read_version_verified_before", None)
            if not callable(bounded_read):
                raise RuntimeError("bounded coverage object transport unavailable")
            body = bounded_read(
                record.object_receipt.expectation,
                record.object_receipt.object_version,
                self._deadline,
            )
            remaining_recovery_time(self._deadline)
            if self._reader._get_record(self._session, artifact_id) != record:
                raise ValueError("coverage Artifact changed while reading")
        if len(body) > max_bytes or self.get_payload(artifact_id) != before:
            raise ValueError("coverage Artifact changed while reading")
        return body

    def read_payload_bytes(self, artifact_id: ArtifactId) -> bytes:
        return self.read_payload_bytes_bounded(artifact_id, max_bytes=32 * 1024 * 1024)

    def store_payload(
        self, payload: ArtifactPayloadWrite, *, artifact_id: ArtifactId | None = None
    ) -> StoredArtifactPayload:
        raise ValueError("coverage report readers cannot publish Artifacts")

    def prune_payload(
        self, artifact_id: ArtifactId, *, pruned_at: datetime | None = None
    ) -> StoredArtifactPayload | None:
        raise ValueError("coverage report readers cannot prune Artifacts")

    def sweep_expired_payloads(
        self, *, as_of: datetime | None = None
    ) -> list[StoredArtifactPayload]:
        raise ValueError("coverage report readers cannot sweep Artifacts")

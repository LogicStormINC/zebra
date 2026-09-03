from __future__ import annotations

from agent_core.domain.artifact_objects import (
    ArtifactObjectIntegrityError,
    ArtifactObjectUnavailableError,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.artifact_payloads import ArtifactPayloadLifecycleStatus
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadLifecycleStatus,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.cloud_artifact_requests import ArtifactMetadataQuery
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports import (
    ArtifactPayloadObjectReadPort,
    ArtifactPayloadReadInspection,
    ArtifactPayloadReadPort,
    ArtifactPayloadReadPrunedError,
    ArtifactPayloadReadStatus,
    ArtifactPayloadReadUnavailableError,
    ArtifactPayloadStorePort,
    CloudArtifactPayloadStorePort,
)

from agent_storage.artifact_projection import artifact_id_from_uri


class LocalArtifactPayloadReader(ArtifactPayloadReadPort):
    """Expose the existing local payload store through the read-only contract."""

    def __init__(self, store: ArtifactPayloadStorePort) -> None:
        self._store = store

    def describe_payload(
        self,
        session_id: SessionId,
        uri: str,
    ) -> ArtifactPayloadReadInspection | None:
        artifact_id = artifact_id_from_uri(uri)
        if artifact_id is None:
            return None
        payload = self._store.get_payload(artifact_id)
        if payload is None or payload.session_id != session_id:
            return None
        status = (
            ArtifactPayloadReadStatus.PRUNED
            if payload.lifecycle_status is ArtifactPayloadLifecycleStatus.PRUNED
            else ArtifactPayloadReadStatus.AVAILABLE
        )
        return ArtifactPayloadReadInspection(
            artifact_id=payload.artifact_id,
            session_id=payload.session_id,
            mime_type=payload.mime_type,
            file_name=None,
            size_bytes=payload.size_bytes,
            status=status,
            lifecycle_status=payload.lifecycle_status.value,
            retained_until=payload.retained_until,
            pruned_at=payload.pruned_at,
        )

    def inspect_payload(
        self,
        session_id: SessionId,
        uri: str,
    ) -> ArtifactPayloadReadInspection | None:
        described = self.describe_payload(session_id, uri)
        if described is None or described.status is ArtifactPayloadReadStatus.PRUNED:
            return described
        inspected = self._store.inspect_payload(described.artifact_id)
        if inspected is not None and inspected.status.value == "missing":
            return described.model_copy(update={"status": ArtifactPayloadReadStatus.MISSING})
        return described

    def read_payload_bytes(
        self,
        session_id: SessionId,
        uri: str,
    ) -> bytes:
        inspection = self.describe_payload(session_id, uri)
        if inspection is None:
            raise FileNotFoundError("artifact payload metadata was not found")
        if inspection.status is ArtifactPayloadReadStatus.PRUNED:
            raise ArtifactPayloadReadPrunedError("artifact payload has been pruned")
        return self._store.read_payload_bytes(inspection.artifact_id)

    def controls(self, store: ArtifactPayloadStorePort) -> bool:
        return self._store is store


class CloudArtifactPayloadReader(ArtifactPayloadReadPort):
    """Compose PostgreSQL lifecycle facts with verified immutable object evidence."""

    def __init__(
        self,
        metadata: CloudArtifactPayloadStorePort,
        objects: ArtifactPayloadObjectReadPort,
        *,
        deployment_namespace: str,
    ) -> None:
        self._metadata = metadata
        self._objects = objects
        self._namespace = deployment_namespace

    def describe_payload(
        self,
        session_id: SessionId,
        uri: str,
    ) -> ArtifactPayloadReadInspection | None:
        artifact_id = _cloud_artifact_id(uri)
        if artifact_id is None:
            return None
        record = self._get_record(session_id, artifact_id)
        if record is None:
            return None
        status = _cloud_read_status(record.lifecycle_status)
        return ArtifactPayloadReadInspection(
            artifact_id=record.artifact_id,
            session_id=record.session_id,
            mime_type=record.reservation.mime_type,
            file_name=record.reservation.file_name,
            size_bytes=record.reservation.size_bytes,
            status=status,
            lifecycle_status=_cloud_lifecycle_status(record.lifecycle_status),
            retained_until=record.reservation.retained_until,
            pruned_at=record.pruned_at,
            bound_event_id=(
                record.event_binding.event_id if record.event_binding is not None else None
            ),
            bound_event_sequence=(
                record.event_binding.sequence if record.event_binding is not None else None
            ),
        )

    def inspect_payload(
        self,
        session_id: SessionId,
        uri: str,
    ) -> ArtifactPayloadReadInspection | None:
        inspection = self.describe_payload(session_id, uri)
        if inspection is None:
            return None
        status = inspection.status
        if status is ArtifactPayloadReadStatus.AVAILABLE:
            record = self._get_record(session_id, inspection.artifact_id)
            assert record is not None
            assert record.object_receipt is not None
            try:
                verification = self._objects.verify(record.object_receipt.expectation)
            except (ArtifactObjectIntegrityError, ArtifactObjectUnavailableError):
                status = ArtifactPayloadReadStatus.UNAVAILABLE
            else:
                if verification.status is ArtifactObjectVerificationStatus.NOT_FOUND:
                    status = ArtifactPayloadReadStatus.MISSING
                elif verification.status is ArtifactObjectVerificationStatus.MISMATCH:
                    status = ArtifactPayloadReadStatus.UNAVAILABLE
                elif (
                    verification.receipt is None
                    or verification.receipt.object_version
                    != record.object_receipt.object_version
                ):
                    status = ArtifactPayloadReadStatus.UNAVAILABLE
        return inspection.model_copy(update={"status": status})

    def read_payload_bytes(
        self,
        session_id: SessionId,
        uri: str,
    ) -> bytes:
        artifact_id = _cloud_artifact_id(uri)
        if artifact_id is None:
            raise FileNotFoundError("artifact payload URI is not canonical")
        record = self._get_record(session_id, artifact_id)
        if record is None:
            raise FileNotFoundError("artifact payload metadata was not found")
        if record.lifecycle_status is CloudArtifactPayloadLifecycleStatus.PRUNED:
            raise ArtifactPayloadReadPrunedError("artifact payload has been pruned")
        if record.lifecycle_status is not CloudArtifactPayloadLifecycleStatus.FINALIZED:
            raise ArtifactPayloadReadUnavailableError("artifact payload is not finalized")
        assert record.object_receipt is not None
        return self._objects.read_version_verified(
            record.object_receipt.expectation,
            record.object_receipt.object_version,
        )

    def _get_record(
        self,
        session_id: SessionId,
        artifact_id: ArtifactId,
    ) -> CloudArtifactPayloadRecord | None:
        return self._metadata.get_metadata(
            ArtifactMetadataQuery(
                deployment_namespace=self._namespace,
                artifact_id=artifact_id,
                session_id=session_id,
            )
        )


def _cloud_read_status(
    status: CloudArtifactPayloadLifecycleStatus,
) -> ArtifactPayloadReadStatus:
    if status is CloudArtifactPayloadLifecycleStatus.FINALIZED:
        return ArtifactPayloadReadStatus.AVAILABLE
    if status is CloudArtifactPayloadLifecycleStatus.PRUNED:
        return ArtifactPayloadReadStatus.PRUNED
    return ArtifactPayloadReadStatus.UNAVAILABLE


def _cloud_lifecycle_status(status: CloudArtifactPayloadLifecycleStatus) -> str:
    if status is CloudArtifactPayloadLifecycleStatus.FINALIZED:
        return ArtifactPayloadLifecycleStatus.ACTIVE.value
    if status is CloudArtifactPayloadLifecycleStatus.PRUNED:
        return ArtifactPayloadLifecycleStatus.PRUNED.value
    return status.value


def _cloud_artifact_id(uri: str) -> ArtifactId | None:
    artifact_id = artifact_id_from_uri(uri)
    if artifact_id is None or uri != f"artifact://{artifact_id}":
        return None
    return artifact_id

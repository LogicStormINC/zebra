from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectReceipt,
    ArtifactObjectVerification,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadLifecycleStatus,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.cloud_artifact_requests import ArtifactEventBinding, ArtifactReserveRequest
from agent_core.domain.identifiers import EventId, new_artifact_id, new_session_id
from agent_core.ports import ArtifactPayloadObjectReadPort, CloudArtifactPayloadStorePort
from agent_storage import (
    CloudArtifactPayloadReader,
    LocalArtifactPayloadReader,
    SQLiteArtifactPayloadStore,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
PAYLOAD = b"pytest passed\n"


class MetadataStub:
    def __init__(self, record: CloudArtifactPayloadRecord | None) -> None:
        self.record = record

    def get_metadata(self, query):  # type: ignore[no-untyped-def]
        record = self.record
        if record is None:
            return None
        if (
            query.deployment_namespace != record.deployment_namespace
            or query.artifact_id != record.artifact_id
            or query.session_id != record.session_id
        ):
            return None
        return record


class ObjectStub:
    def __init__(
        self,
        status: ArtifactObjectVerificationStatus,
        *,
        object_version: str = "v1",
    ) -> None:
        self.status = status
        self.object_version = object_version
        self.read_count = 0

    def verify(self, expectation: ArtifactObjectExpectation) -> ArtifactObjectVerification:
        return ArtifactObjectVerification(
            expectation=expectation,
            status=self.status,
            receipt=(
                ArtifactObjectReceipt(
                    expectation=expectation,
                    object_version=self.object_version,
                    verified_at=NOW,
                )
                if self.status is ArtifactObjectVerificationStatus.VERIFIED
                else None
            ),
        )

    def read_version_verified(
        self,
        expectation: ArtifactObjectExpectation,
        object_version: str,
    ) -> bytes:
        self.read_count += 1
        assert object_version == "v1"
        return PAYLOAD


@pytest.mark.parametrize(
    ("lifecycle", "object_status", "expected"),
    [
        ("finalized", "verified", "payload_available"),
        ("finalized", "not_found", "payload_missing"),
        ("finalized", "mismatch", "payload_unavailable"),
        ("staged", "verified", "payload_unavailable"),
        ("pruning", "verified", "payload_unavailable"),
        ("pruned", "verified", "payload_pruned"),
    ],
)
def test_cloud_reader_fails_closed_by_lifecycle_and_object_evidence(
    lifecycle: str,
    object_status: str,
    expected: str,
) -> None:
    record = _record(CloudArtifactPayloadLifecycleStatus(lifecycle))
    objects = ObjectStub(ArtifactObjectVerificationStatus(object_status))
    reader = CloudArtifactPayloadReader(
        cast(CloudArtifactPayloadStorePort, MetadataStub(record)),
        cast(ArtifactPayloadObjectReadPort, objects),
        deployment_namespace="tenant-a",
    )

    inspection = reader.inspect_payload(record.session_id, record.uri)

    assert inspection is not None
    assert inspection.status.value == expected
    assert inspection.lifecycle_status == {
        "finalized": "active",
        "pruned": "pruned",
    }.get(lifecycle, lifecycle)


def test_cloud_reader_requires_session_scope_and_finalized_state_for_bytes() -> None:
    finalized = _record(CloudArtifactPayloadLifecycleStatus.FINALIZED)
    objects = ObjectStub(ArtifactObjectVerificationStatus.VERIFIED)
    reader = CloudArtifactPayloadReader(
        cast(CloudArtifactPayloadStorePort, MetadataStub(finalized)),
        cast(ArtifactPayloadObjectReadPort, objects),
        deployment_namespace="tenant-a",
    )

    assert reader.read_payload_bytes(finalized.session_id, finalized.uri) == PAYLOAD
    assert objects.read_count == 1
    with pytest.raises(FileNotFoundError, match="metadata was not found"):
        reader.read_payload_bytes(new_session_id(), finalized.uri)

    staged = _record(CloudArtifactPayloadLifecycleStatus.STAGED)
    staged_reader = CloudArtifactPayloadReader(
        cast(CloudArtifactPayloadStorePort, MetadataStub(staged)),
        cast(ArtifactPayloadObjectReadPort, objects),
        deployment_namespace="tenant-a",
    )
    with pytest.raises(RuntimeError, match="not finalized"):
        staged_reader.read_payload_bytes(staged.session_id, staged.uri)


def test_cloud_reader_rejects_an_unrecorded_object_version() -> None:
    finalized = _record(CloudArtifactPayloadLifecycleStatus.FINALIZED)
    reader = CloudArtifactPayloadReader(
        cast(CloudArtifactPayloadStorePort, MetadataStub(finalized)),
        cast(
            ArtifactPayloadObjectReadPort,
            ObjectStub(
                ArtifactObjectVerificationStatus.VERIFIED,
                object_version="unexpected-v2",
            ),
        ),
        deployment_namespace="tenant-a",
    )

    inspection = reader.inspect_payload(finalized.session_id, finalized.uri)

    assert inspection is not None
    assert inspection.status.value == "payload_unavailable"


def test_cloud_reader_rejects_noncanonical_uri_aliases() -> None:
    finalized = _record(CloudArtifactPayloadLifecycleStatus.FINALIZED)
    reader = CloudArtifactPayloadReader(
        cast(CloudArtifactPayloadStorePort, MetadataStub(finalized)),
        cast(
            ArtifactPayloadObjectReadPort,
            ObjectStub(ArtifactObjectVerificationStatus.VERIFIED),
        ),
        deployment_namespace="tenant-a",
    )

    assert reader.describe_payload(finalized.session_id, f"{finalized.uri}?download=1") is None
    assert reader.describe_payload(
        finalized.session_id,
        f"file:///tmp/{finalized.artifact_id}/payload.txt",
    ) is None


def test_local_reader_preserves_missing_file_inspection(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "local.db")
    session_id = new_session_id()
    payload = store.store_payload(
        ArtifactPayloadWrite(
            session_id=session_id,
            kind="tool-output",
            mime_type="text/plain",
            payload=PAYLOAD,
            created_at=NOW,
        )
    )
    assert payload.access_uri is not None
    Path(payload.access_uri.removeprefix("file://")).unlink()

    inspection = LocalArtifactPayloadReader(store).inspect_payload(
        session_id,
        payload.access_uri,
    )

    assert inspection is not None
    assert inspection.status.value == "payload_missing"


def _record(status: CloudArtifactPayloadLifecycleStatus) -> CloudArtifactPayloadRecord:
    artifact_id = new_artifact_id()
    session_id = new_session_id()
    expectation = ArtifactObjectExpectation(
        deployment_namespace="tenant-a",
        artifact_id=artifact_id,
        sha256=sha256(PAYLOAD).hexdigest(),
        size_bytes=len(PAYLOAD),
    )
    receipt = ArtifactObjectReceipt(
        expectation=expectation,
        object_version="v1",
        verified_at=NOW,
    )
    readable = status in {
        CloudArtifactPayloadLifecycleStatus.FINALIZED,
        CloudArtifactPayloadLifecycleStatus.PRUNING,
        CloudArtifactPayloadLifecycleStatus.PRUNED,
    }
    return CloudArtifactPayloadRecord(
        deployment_namespace="tenant-a",
        reservation=ArtifactReserveRequest(
            artifact_id=artifact_id,
            session_id=session_id,
            intended_event_sequence=1,
            kind="tool-output",
            mime_type="text/plain",
            sha256=expectation.sha256,
            size_bytes=expectation.size_bytes,
            idempotency_key="artifact-1",
            created_at=NOW,
        ),
        lifecycle_status=status,
        lifecycle_revision=1,
        event_binding=(
            ArtifactEventBinding(
                session_id=session_id,
                event_id=EventId(UUID("00000000-0000-0000-0000-000000000001")),
                sequence=1,
                artifact_uri=f"artifact://{artifact_id}",
            )
            if readable
            else None
        ),
        object_receipt=receipt if readable else None,
        finalized_at=NOW if readable else None,
        pruning_at=(
            NOW
            if status
            in {
                CloudArtifactPayloadLifecycleStatus.PRUNING,
                CloudArtifactPayloadLifecycleStatus.PRUNED,
            }
            else None
        ),
        pruned_at=NOW if status is CloudArtifactPayloadLifecycleStatus.PRUNED else None,
    )

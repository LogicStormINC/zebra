"""Coverage Artifact trust-boundary checks without network or database access."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.artifact_payloads import (
    ArtifactPayloadLifecycleStatus,
    StoredArtifactPayload,
)
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports.artifact_payload_store import (
    ArtifactPayloadStorePort,
    BoundedArtifactPayloadReaderPort,
)
from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES, read_artifact


class BoundedStoreSpec(ArtifactPayloadStorePort, BoundedArtifactPayloadReaderPort):
    pass

def payload():
    artifact_id = ArtifactId(uuid4())
    return StoredArtifactPayload(
        artifact_id=artifact_id, session_id=SessionId(uuid4()), kind="coverage-results",
        mime_type="application/json", uri=f"artifact://{artifact_id}",
        sha256=sha256(b"{}").hexdigest(), size_bytes=2,
        lifecycle_status=ArtifactPayloadLifecycleStatus.ACTIVE, created_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("ref", ["https://example.test/result", "file:///tmp/result",
                                  "artifact://../private", "artifact://not-a-uuid"])
def test_untrusted_reference_never_reaches_payload_store(ref):
    artifacts = Mock(spec=ArtifactPayloadStorePort)
    metadata = payload()
    with pytest.raises(ValueError):
        read_artifact(artifacts, ref, metadata.sha256, metadata.session_id)
    artifacts.get_payload.assert_not_called()
    artifacts.read_payload_bytes.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"session_id": SessionId(uuid4())}, {"sha256": "f" * 64},
    {"lifecycle_status": ArtifactPayloadLifecycleStatus.PRUNED},
    {"retained_until": datetime.now(UTC) - timedelta(seconds=1)},
    {"size_bytes": MAX_COVERAGE_ARTIFACT_BYTES + 1},
])
def test_invalid_metadata_fails_before_body_read(changes):
    metadata = payload()
    artifacts = Mock(spec=ArtifactPayloadStorePort)
    artifacts.get_payload.return_value = metadata.model_copy(update=changes)
    with pytest.raises(ValueError):
        read_artifact(artifacts, metadata.uri, metadata.sha256, metadata.session_id)
    artifacts.read_payload_bytes.assert_not_called()


def test_corrupt_bytes_are_rejected():
    metadata = payload()
    artifacts = Mock(spec=BoundedStoreSpec)
    artifacts.get_payload.return_value = metadata
    artifacts.read_payload_bytes_bounded.return_value = b"[]"
    with pytest.raises(ValueError, match="corrupt"):
        read_artifact(artifacts, metadata.uri, metadata.sha256, metadata.session_id)


def test_pruning_racing_the_object_read_is_rejected():
    metadata = payload()
    artifacts = Mock(spec=BoundedStoreSpec)
    artifacts.get_payload.side_effect = [metadata, metadata.model_copy(update={
        "lifecycle_status": ArtifactPayloadLifecycleStatus.PRUNED,
    })]
    artifacts.read_payload_bytes_bounded.return_value = b"{}"
    with pytest.raises(ValueError, match="metadata changed"):
        read_artifact(artifacts, metadata.uri, metadata.sha256, metadata.session_id)

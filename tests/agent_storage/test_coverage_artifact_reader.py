"""Read-only certificate composition retains object and lifecycle evidence."""

import pytest
from agent_core.domain.artifact_objects import ArtifactObjectVerificationStatus
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_core.domain.identifiers import new_session_id
from agent_storage.coverage_artifact_reader import CloudCoverageArtifactReader

from tests.agent_storage.test_artifact_payload_reads import (
    PAYLOAD,
    MetadataStub,
    ObjectStub,
    _record,
)


def reader_for(record, objects=None, **scope):
    return CloudCoverageArtifactReader(
        MetadataStub(record),
        objects or ObjectStub(ArtifactObjectVerificationStatus.VERIFIED),
        deployment_namespace=scope.get("deployment", "tenant-a"),
        session_id=scope.get("session", record.session_id),
    )


def test_finalized_original_reads_and_mutations_are_forbidden():
    record = _record(CloudArtifactPayloadLifecycleStatus.FINALIZED)
    objects = ObjectStub(ArtifactObjectVerificationStatus.VERIFIED)
    reader = reader_for(record, objects)
    assert reader.read_payload_bytes_bounded(record.artifact_id, max_bytes=len(PAYLOAD)) == PAYLOAD
    assert objects.read_count == 1
    assert reader.get_payload(record.artifact_id).sha256 == record.reservation.sha256
    for mutate in (
        lambda: reader.store_payload(None),
        lambda: reader.prune_payload(record.artifact_id),
        reader.sweep_expired_payloads,
    ):
        with pytest.raises(ValueError, match="readers cannot"):
            mutate()


@pytest.mark.parametrize("scope", [{"deployment": "other"}, {"session": new_session_id()}])
def test_scope_mismatch_refuses_before_object_reads(scope):
    record = _record(CloudArtifactPayloadLifecycleStatus.FINALIZED)
    objects = ObjectStub(ArtifactObjectVerificationStatus.VERIFIED)
    reader = reader_for(record, objects, **scope)
    assert reader.get_payload(record.artifact_id) is None
    with pytest.raises(ValueError, match="unavailable"):
        reader.read_payload_bytes(record.artifact_id)
    assert objects.read_count == 0


def test_bound_refusal_and_pruning_race():
    record = _record(CloudArtifactPayloadLifecycleStatus.FINALIZED)
    metadata = MetadataStub(record)

    class Pruner(ObjectStub):
        def read_version_verified(self, expectation, version):
            metadata.record = None
            return super().read_version_verified(expectation, version)

    objects = Pruner(ArtifactObjectVerificationStatus.VERIFIED)
    reader = CloudCoverageArtifactReader(
        metadata,
        objects,
        deployment_namespace="tenant-a",
        session_id=record.session_id,
    )
    with pytest.raises(ValueError, match="read bound"):
        reader.read_payload_bytes_bounded(record.artifact_id, max_bytes=len(PAYLOAD) - 1)
    assert objects.read_count == 0
    with pytest.raises(ValueError, match="changed"):
        reader.read_payload_bytes(record.artifact_id)
    assert objects.read_count == 1

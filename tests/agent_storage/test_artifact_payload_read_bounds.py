"""Bounded reads pin one metadata receipt before any exact-version object I/O."""

import pytest
from agent_core.domain.artifact_objects import ArtifactObjectVerificationStatus
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_core.ports import ArtifactPayloadReadUnavailableError
from agent_storage.artifact_payload_reads import CloudArtifactPayloadReader

from tests.agent_storage.test_artifact_payload_reads import (
    PAYLOAD,
    MetadataStub,
    ObjectStub,
    _record,
)


@pytest.mark.parametrize("bound", [True, False, 0, -1, "14", 14.0])
def test_invalid_ceiling_refuses_before_metadata_or_object_io(bound):
    class NoReads:
        def get_metadata(self, query):
            raise AssertionError("invalid bound cannot access metadata")

    reader = CloudArtifactPayloadReader(NoReads(), None, deployment_namespace="tenant-a")
    with pytest.raises(ValueError, match="positive integer"):
        reader.read_payload_bytes(None, "invalid", max_bytes=bound)


def test_excess_size_refuses_before_original_read_and_exact_size_is_supported():
    record = _record(CloudArtifactPayloadLifecycleStatus.FINALIZED)
    objects = ObjectStub(ArtifactObjectVerificationStatus.VERIFIED)
    reader = CloudArtifactPayloadReader(
        MetadataStub(record), objects, deployment_namespace="tenant-a"
    )
    with pytest.raises(ArtifactPayloadReadUnavailableError, match="byte ceiling"):
        reader.read_payload_bytes(record.session_id, record.uri, max_bytes=len(PAYLOAD) - 1)
    assert objects.read_count == 0
    assert (
        reader.read_payload_bytes(record.session_id, record.uri, max_bytes=len(PAYLOAD)) == PAYLOAD
    )
    assert objects.read_count == 1
    assert reader.read_payload_bytes(record.session_id, record.uri) == PAYLOAD
    assert objects.read_count == 2


def test_bound_and_object_read_use_one_pinned_metadata_record():
    record = _record(CloudArtifactPayloadLifecycleStatus.FINALIZED)

    class Once(MetadataStub):
        reads = 0

        def get_metadata(self, query):
            self.reads += 1
            assert self.reads == 1, "do not describe, then resolve a different record"
            return super().get_metadata(query)

    class Pinned(ObjectStub):
        def read_version_verified(self, expectation, version):
            assert expectation == record.object_receipt.expectation
            assert version == record.object_receipt.object_version
            return super().read_version_verified(expectation, version)

    metadata = Once(record)
    objects = Pinned(ArtifactObjectVerificationStatus.VERIFIED)
    reader = CloudArtifactPayloadReader(metadata, objects, deployment_namespace="tenant-a")
    assert (
        reader.read_payload_bytes(record.session_id, record.uri, max_bytes=len(PAYLOAD)) == PAYLOAD
    )
    assert metadata.reads == objects.read_count == 1

"""Optional real PostgreSQL + versioned S3 proof; no mock object client."""

import json
import os
import selectors
import subprocess
import sys
from time import monotonic

import pytest
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadRecord
from agent_storage import S3ArtifactObjectStore
from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts

from tests.agent_storage.test_coverage_artifact_publication import (
    _authority,
    _publish,
    _publisher,
    publication,  # noqa: F401 - imported pytest fixture
)
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import dsn, source_counts  # noqa: F401
from tests.agent_storage.test_postgres_coverage import env as postgres_env  # noqa: F401
from tests.agent_storage.test_s3_artifact_objects_minio import _client

_CONCURRENT_PUBLISHER = r"""
import json
import os
import sys
from uuid import UUID

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadConflictError
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.identifiers import ArtifactId
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_storage import (
    PostgresCloudArtifactPayloadStore, PostgresEventStore, S3ArtifactObjectStore,
)
from agent_storage.event_rows import SessionEventSequenceConflictError
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher
from tests.agent_storage.test_s3_artifact_objects_minio import _client

data = json.loads(sys.stdin.readline())
binding = CoverageRunBinding.model_validate_json(data['binding'])
payload = ArtifactPayloadWrite.model_validate_json(data['payload'])
authority = WorkerMutationAuthority.model_validate_json(data['authority'])
dsn = os.environ['ZEBRA_PROCESS_POSTGRES_DSN']
deployment = authority.deployment_namespace
metadata = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=deployment)
events = PostgresEventStore(dsn, deployment_namespace=deployment)
objects = S3ArtifactObjectStore(_client(), bucket=os.environ['ZEBRA_TEST_S3_BUCKET'])
publisher = PostgresCoverageArtifactPublisher(
    dsn, deployment_namespace=deployment, metadata=metadata, objects=objects,
)

def barrier(stage):
    print(json.dumps({'stage': stage, 'pid': os.getpid()}), flush=True)
    if sys.stdin.readline().strip() != 'go':
        raise RuntimeError('parent did not release publisher barrier')

put = objects.put_if_absent
synchronized = False

def concurrent_put(request):
    global synchronized
    if not synchronized:
        synchronized = True
        barrier('put')  # Both processes reserved the same Artifact before either upload.
    return put(request)

objects.put_if_absent = concurrent_put
barrier('ready')
for attempt in range(3):
    try:
        record = publisher.publish(
            binding, payload, artifact_id=ArtifactId(UUID(data['artifact_id'])),
            authority=authority, check_authority=lambda: None,
        )
        print(record.model_dump_json(), flush=True)
        break
    except CloudArtifactPayloadConflictError as error:
        if str(error) not in {
            'artifact reservation stream revision is stale',
            'artifact mutation stream revision is stale',
            'coverage publication changed during object verification',
            'coverage reservation batch raced',
        }:
            raise
        if attempt == 2:
            raise
    except SessionEventSequenceConflictError:
        if attempt == 2:
            raise
    authority = authority.model_copy(update={
        'expected_stream_revision': events.list_for_session(binding.session_id)[-1].sequence,
    })
"""


def _release_publishers(children, stage):
    deadline = monotonic() + 20
    with selectors.DefaultSelector() as selector:
        for child in children:
            selector.register(child.stdout, selectors.EVENT_READ, child)
        while selector.get_map():
            ready = selector.select(max(0, deadline - monotonic()))
            assert ready, f"publisher barrier {stage} timed out"
            for key, _ in ready:
                message = key.fileobj.readline()
                assert message, "publisher exited before barrier; stderr withheld"
                assert json.loads(message) == {"stage": stage, "pid": key.data.pid}
                selector.unregister(key.fileobj)
    for child in children:
        child.stdin.write("go\n")
        child.stdin.flush()


def test_real_services_resume_uploaded_object_and_atomically_finalize(publication, monkeypatch):  # noqa: F811
    env = publication
    bucket = os.environ.get("ZEBRA_TEST_S3_BUCKET")
    if not bucket:
        pytest.skip("explicit isolated ZEBRA_TEST_S3_BUCKET required")
    env.objects = S3ArtifactObjectStore(_client(), bucket=bucket)
    env.publisher = _publisher(env)
    original = env.publisher._record_receipts

    def crash_after_upload(*args, **kwargs):
        raise RuntimeError("receipt process crashed after actual S3 upload")

    monkeypatch.setattr(env.publisher, "_record_receipts", crash_after_upload)
    before = source_counts(env)
    with pytest.raises(RuntimeError, match="receipt process crashed"):
        _publish(env)
    assert source_counts(env) == before
    monkeypatch.setattr(env.publisher, "_record_receipts", original)
    env.publisher = _publisher(env)
    result = _publish(env, authority=_authority(env))
    assert result.object_receipt is not None
    assert result.object_receipt.object_version != "null"
    assert source_counts(env) == before + 1
    assert _publish(env, authority=_authority(env)) == result
    assert source_counts(env) == before + 1
    from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE

    facade = CloudCoverageArtifacts(
        binding=env.binding,
        deployment_namespace=NAMESPACE,
        metadata=env.metadata,
        objects=env.objects,
        publisher=env.publisher,
        authority=lambda: _authority(env),
        check_authority=lambda: None,
        sync_events=lambda: None,
    )
    assert (
        facade.read_payload_bytes_bounded(
            env.artifact_id,
            max_bytes=len(env.payload.payload),
        )
        == env.payload.payload
    )


def test_real_services_two_processes_publish_one_artifact(publication):  # noqa: F811
    from agent_core.domain.events import EventType

    env = publication
    bucket = os.environ.get("ZEBRA_TEST_S3_BUCKET")
    if not bucket:
        pytest.skip("explicit isolated ZEBRA_TEST_S3_BUCKET required")
    client = _client()
    assert client.get_bucket_versioning(Bucket=bucket).get("Status") == "Enabled"
    env.objects = S3ArtifactObjectStore(client, bucket=bucket)
    env.publisher = _publisher(env)
    before = source_counts(env)
    # The parent fixture owns the unique schema; children open independent connections.
    child_env = {**os.environ, "ZEBRA_PROCESS_POSTGRES_DSN": env.dsn}
    request = json.dumps({
        "binding": env.binding.model_dump_json(), "payload": env.payload.model_dump_json(),
        "authority": _authority(env).model_dump_json(), "artifact_id": str(env.artifact_id),
    }) + "\n"
    children = []
    try:
        for _ in range(2):
            child = subprocess.Popen(
                [sys.executable, "-c", _CONCURRENT_PUBLISHER],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=child_env,
            )
            children.append(child)
            child.stdin.write(request)
            child.stdin.flush()
        assert len({child.pid for child in children}) == 2
        assert all(child.pid != os.getpid() for child in children)
        _release_publishers(children, "ready")
        _release_publishers(children, "put")
        records = []
        for child in children:
            output, _stderr = child.communicate(timeout=30)
            assert child.returncode == 0, "publisher child failed; stderr withheld"
            records.append(CloudArtifactPayloadRecord.model_validate_json(output))
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
    assert records[0] == records[1]
    record = records[0]
    assert record.lifecycle_status.value == "finalized"
    assert record.object_receipt is not None and record.event_binding is not None
    assert record.object_receipt.object_version != "null"
    assert source_counts(env) == before + 1
    events = env.events.list_for_session(env.session.session_id)
    materialized = [event for event in events
                    if event.event_type == EventType.COVERAGE_ARTIFACT_MATERIALIZED]
    assert len(materialized) == 1
    assert record.event_binding.event_id == materialized[0].event_id
    assert materialized[0].payload["metadata"]["artifact_uri"] == record.uri
    assert _publish(env, authority=_authority(env)) == record
    with pytest.raises(ValueError, match="immutable publication conflicts"):
        _publish(env, payload=env.payload.model_copy(update={"payload": b"conflicting bytes"}),
                 authority=_authority(env))
    receipt = record.object_receipt
    assert env.objects.read_version_verified(receipt.expectation, receipt.object_version) == (
        env.payload.payload
    )
    key = env.objects._key(receipt.expectation)
    versions = client.list_object_versions(Bucket=bucket, Prefix=key)
    assert not versions.get("IsTruncated")
    assert not versions.get("DeleteMarkers")
    assert [(item["Key"], item["VersionId"]) for item in versions.get("Versions", [])] == [
        (key, receipt.object_version),
    ]
    assert source_counts(env) == before + 1

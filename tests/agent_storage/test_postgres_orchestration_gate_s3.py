"""Opt-in real S3/PG gate proof; parent admission and trusted counter remain fixtures."""

import os
from hashlib import sha256

import psycopg
import pytest
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_core.domain.cloud_artifact_requests import ArtifactMetadataQuery
from agent_core.domain.events import EventType
from agent_storage import PostgresCloudArtifactPayloadStore, S3ArtifactObjectStore
from agent_storage.postgres.events import PostgresEventStore

from tests.agent_storage.test_postgres_orchestration_gate import _observations
from tests.agent_storage.test_postgres_orchestration_gate import native as shared_native
from tests.agent_storage.test_postgres_orchestration_gate import terminal as shared_terminal
from tests.worker.cloud_artifact_test_objects import bucket, s3_client

native = shared_native
terminal = shared_terminal


@pytest.fixture
def gate_s3_objects():
    required = (
        "ZEBRA_TEST_S3_ENDPOINT",
        "ZEBRA_TEST_S3_ACCESS_KEY",
        "ZEBRA_TEST_S3_SECRET_KEY",
        "ZEBRA_TEST_S3_BUCKET",
    )
    configured = [bool(os.environ.get(name)) for name in required]
    if not any(configured):
        pytest.skip("requires explicitly owned ZEBRA_TEST_S3_* service and versioned bucket")
    assert all(configured), "partial real S3 configuration; refusing fixture fallback"
    client = s3_client()
    try:
        assert client.get_bucket_versioning(Bucket=bucket())["Status"] == "Enabled"
        yield S3ArtifactObjectStore(client, bucket=bucket())
    finally:
        client.close()


@pytest.mark.parametrize("terminal", ["real_s3"], indirect=True)
@pytest.mark.parametrize(
    "native",
    [{"evaluation_profile_ref": "evaluation-profile/orchestration-readonly@1"}],
    indirect=True,
)
def test_real_file_read_versioned_s3_finalization_and_immutable_gate_replay(
    terminal, gate_s3_objects
):
    factory, runtime, run, child, budget = terminal
    events = PostgresEventStore(
        factory.database._dsn, deployment_namespace=factory.namespace
    ).list_for_session(budget.session_id)
    tool_event = next(e for e in events if e.event_type is EventType.TOOL_EXECUTION_COMPLETED)
    with factory.database.connect() as c:
        rows = c.execute(
            "SELECT artifact_id,object_version,object_verified_at,lifecycle_status "
            "FROM artifact_payload_metadata WHERE deployment_namespace=%s AND session_id=%s",
            (factory.namespace, budget.session_id),
        ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    metadata = PostgresCloudArtifactPayloadStore(
        factory.database._dsn, deployment_namespace=factory.namespace
    ).get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=factory.namespace,
            artifact_id=row["artifact_id"],
            session_id=budget.session_id,
        )
    )
    assert metadata is not None
    assert metadata.lifecycle_status is CloudArtifactPayloadLifecycleStatus.FINALIZED
    assert row["lifecycle_status"] == "finalized" and row["object_verified_at"] is not None
    assert metadata.event_binding is not None and metadata.object_receipt is not None
    assert metadata.event_binding.event_id == tool_event.event_id
    assert metadata.event_binding.sequence == tool_event.sequence
    assert metadata.uri == tool_event.payload["metadata"]["artifact_uri"]
    receipt = metadata.object_receipt
    assert receipt.object_version and receipt.object_version != "null"
    assert receipt.object_version == row["object_version"]
    assert receipt.verified_at == row["object_verified_at"]
    # Read the exact finalized version, not whichever object happens to be current.
    payload = gate_s3_objects.read_version_verified(receipt.expectation, receipt.object_version)
    assert payload == b"actual FileReadTool evidence"
    assert sha256(payload).hexdigest() == metadata.reservation.sha256 == receipt.expectation.sha256
    assert len(payload) == metadata.reservation.size_bytes == receipt.expectation.size_bytes
    assert factory.store.read_run_status(run.run_ref) == "running"

    runtime.synthesize(run.run_ref)
    original = _observations(factory, run)
    assert len(original) == 1 and original[0]["evaluation"]["passed"] is True
    facts = original[0]["facts"]
    assert facts["policy"]["semantics"]["review_required"] is False
    observed = facts["children"][0]
    assert observed["child_task_id"] == child.child_task_id
    assert observed["artifacts"] == [
        {
            "artifact_id": str(metadata.artifact_id),
            "sha256": metadata.reservation.sha256,
            "event_id": str(tool_event.event_id),
            "lifecycle_revision": str(metadata.lifecycle_revision),
        }
    ]
    assert any(
        t["event_id"] == str(tool_event.event_id) and t["successful"] for t in observed["tools"]
    )
    assert factory.store.read_completion_receipt(run.run_ref, 1, original[0]["input_digest"])
    assert (
        factory.store.read_completion_receipt(run.run_ref, 2, original[0]["input_digest"]) is None
    )
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with factory.database.connect() as c:
            c.execute(
                "UPDATE orchestration_completion_observations SET facts='{}' "
                "WHERE deployment_namespace=%s AND run_id=%s",
                (factory.namespace, run.run_ref),
            )
    runtime.synthesize(run.run_ref)
    assert factory.store.read_run_status(run.run_ref) == "completed"
    assert _observations(factory, run) == original
    assert (
        gate_s3_objects.read_version_verified(receipt.expectation, receipt.object_version)
        == payload
    )

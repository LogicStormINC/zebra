"""Real PostgreSQL publication/recovery with the existing versioned fake S3 store."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_core.domain.cloud_artifact_requests import (
    ArtifactMetadataQuery,
    canonical_artifact_reserve_hash,
)
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseLostError
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_storage import (
    PostgresCloudArtifactPayloadStore,
    PostgresEventStore,
    S3ArtifactObjectStore,
)
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import (  # noqa: F401
    batch,
    bind,
    dsn,
    source_counts,
)
from tests.agent_storage.test_postgres_coverage import env as postgres_env  # noqa: F401
from tests.agent_storage.test_s3_artifact_objects import _FakeS3Client


@pytest.fixture
def publication(postgres_env):  # noqa: F811
    env = postgres_env
    bind(env)
    env.events = PostgresEventStore(env.dsn, deployment_namespace=NAMESPACE)
    env.metadata = PostgresCloudArtifactPayloadStore(env.dsn, deployment_namespace=NAMESPACE)
    env.client = _FakeS3Client()
    env.objects = S3ArtifactObjectStore(env.client, bucket="coverage-tests")
    env.publisher = _publisher(env)
    env.artifact_id = ArtifactId(uuid4())
    env.payload = ArtifactPayloadWrite(
        session_id=env.session.session_id, kind="coverage-results", mime_type="application/json",
        payload=b'{"results":[]}', created_at=datetime.now(UTC),
    )
    env.authority = _authority(env)
    return env


def _publisher(env):
    return PostgresCoverageArtifactPublisher(
        env.dsn, deployment_namespace=NAMESPACE, metadata=env.metadata, objects=env.objects,
    )


def _authority(env):
    return WorkerMutationAuthority(
        deployment_namespace=NAMESPACE, session_id=env.session.session_id,
        expected_stream_revision=env.events.list_for_session(env.session.session_id)[-1].sequence,
        lease_fence=env.fence,
    )


def _metadata(env):
    return env.metadata.get_metadata(ArtifactMetadataQuery(
        deployment_namespace=NAMESPACE, artifact_id=env.artifact_id,
        session_id=env.session.session_id,
    ))


def _publish(env, *, check_authority=lambda: None, binding=None, payload=None, authority=None):
    return env.publisher.publish(
        env.binding if binding is None else binding,
        env.payload if payload is None else payload,
        artifact_id=env.artifact_id, authority=env.authority if authority is None else authority,
        check_authority=check_authority,
    )


def _crash(env, monkeypatch, stage):
    target, method = (
        (env.objects, "put_if_absent") if stage == "upload"
        else (env.publisher, "_record_receipts")
    )
    original = getattr(target, method)

    def lost_acknowledgement(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError(f"crash after {stage}")

    before = source_counts(env)
    with monkeypatch.context() as patch:
        patch.setattr(target, method, lost_acknowledgement)
        with pytest.raises(RuntimeError, match=f"crash after {stage}"):
            _publish(env)
    staged = _metadata(env)
    assert staged.lifecycle_status == CloudArtifactPayloadLifecycleStatus.STAGED
    # Uploads survive, but receipt and Event settlement share one transaction.
    assert staged.lifecycle_revision == 0
    assert staged.object_receipt is None
    assert staged.event_binding is None
    assert len(env.client.objects) == 1
    assert source_counts(env) == before
    return staged


def _replace_worker(env):
    env.leases.release(env.session.session_id, fence=env.fence)
    lease = env.leases.acquire(
        env.session.session_id, owner_instance_id="replacement-coverage-worker",
        ttl=timedelta(minutes=5),
    )
    env.fence = lease.fence
    env.authority = _authority(env)
    env.publisher = _publisher(env)


def _assert_finalized(env, record):
    assert _metadata(env) == record
    assert record.lifecycle_status == CloudArtifactPayloadLifecycleStatus.FINALIZED
    assert record.lifecycle_revision == 2
    event = env.events.list_for_session(env.session.session_id)[-1]
    assert event.event_type == EventType.COVERAGE_ARTIFACT_MATERIALIZED
    assert event.event_id == record.event_binding.event_id
    assert event.sequence == record.event_binding.sequence
    assert record.reservation.intended_event_sequence == event.sequence
    assert event.payload["namespace"] == env.binding.namespace
    assert event.payload["run_id"] == env.binding.run_id
    assert event.payload["metadata"]["artifact_uri"] == record.uri
    assert event.payload["sha256"] == sha256(env.payload.payload).hexdigest()
    assert event.payload["reservation"] == canonical_artifact_reserve_hash(
        NAMESPACE, record.reservation,
    )
    assert env.objects.read_version_verified(
        record.object_receipt.expectation, record.object_receipt.object_version,
    ) == env.payload.payload
    return event


def test_fresh_publication_atomically_finalizes_canonical_event_and_retry(publication):
    env = publication
    before = source_counts(env)
    record = _publish(env)
    _assert_finalized(env, record)
    assert source_counts(env) == before + 1
    assert _publish(env) == record
    assert source_counts(env) == before + 1
    assert len(env.client.objects) == 1


@pytest.mark.parametrize("stage", ["upload", "receipt"])
def test_crashed_publication_resumes_with_replacement_fence_after_stream_growth(
    publication, monkeypatch, stage,
):
    env = publication
    staged = _crash(env, monkeypatch, stage)
    env.store.commit(batch(env), fence=env.fence)
    _replace_worker(env)
    assert env.authority.expected_stream_revision >= staged.reservation.intended_event_sequence
    before = source_counts(env)
    record = _publish(env)
    event = _assert_finalized(env, record)
    assert event.sequence > staged.reservation.intended_event_sequence
    assert event.payload["previous_reservation"] == canonical_artifact_reserve_hash(
        NAMESPACE, staged.reservation,
    )
    assert event.payload["previous_reservation"] != event.payload["reservation"]
    assert source_counts(env) == before + 1
    assert len(env.client.objects) == 1
    assert _publish(env) == record
    assert source_counts(env) == before + 1


@pytest.mark.parametrize("stage", ["fresh", "upload", "receipt", "finalized"])
def test_old_worker_fence_cannot_publish_or_resume(publication, monkeypatch, stage):
    env = publication
    if stage in {"upload", "receipt"}:
        _crash(env, monkeypatch, stage)
    elif stage == "finalized":
        _publish(env)
    old_authority = env.authority
    _replace_worker(env)
    before, metadata = source_counts(env), _metadata(env)
    with pytest.raises(LeaseLostError):
        _publish(env, authority=old_authority)
    assert source_counts(env) == before
    assert _metadata(env) == metadata


def test_revocation_before_finalize_rolls_back_event_and_metadata_rebinding(
    publication, monkeypatch,
):
    env = publication
    staged = _crash(env, monkeypatch, "receipt")
    env.store.commit(batch(env), fence=env.fence)
    _replace_worker(env)
    before = source_counts(env)
    calls = 0

    def check_authority():
        nonlocal calls
        calls += 1
        if _metadata(env).lifecycle_status == CloudArtifactPayloadLifecycleStatus.FINALIZED:
            # The transaction has appended the Event and rebound the metadata;
            # another connection must still see the staged, committed version.
            # A nested adapter now deliberately borrows the caller's transaction.
            # A fresh thread (without its ContextVar) is the independent observer.
            with ThreadPoolExecutor(max_workers=1) as observer:
                assert observer.submit(source_counts, env).result() == before
                assert observer.submit(_metadata, env).result() == staged
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        _publish(env, check_authority=check_authority)
    assert calls > 3
    assert source_counts(env) == before
    assert _metadata(env) == staged
    _assert_finalized(env, _publish(env))
    assert source_counts(env) == before + 1


def test_same_identity_with_different_payload_conflicts(publication):
    env = publication
    record = _publish(env)
    before = source_counts(env)
    with pytest.raises(ValueError, match="immutable publication conflicts"):
        _publish(env, payload=env.payload.model_copy(update={"payload": b'{"changed":true}'}))
    assert source_counts(env) == before
    assert _metadata(env) == record
    assert len(env.client.objects) == 1


@pytest.mark.parametrize("stage", ["upload", "receipt", "finalized"])
def test_same_artifact_cannot_be_claimed_by_foreign_run(publication, monkeypatch, stage):
    env = publication
    if stage == "finalized":
        _publish(env)
    else:
        _crash(env, monkeypatch, stage)
    foreign = env.binding.model_copy(update={"run_id": "foreign-run"})
    env.store.bind(foreign, fence=env.fence)
    env.authority = _authority(env)
    before, metadata = source_counts(env), _metadata(env)
    with pytest.raises(ValueError, match="different run"):
        _publish(env, binding=foreign)
    assert source_counts(env) == before
    assert _metadata(env) == metadata

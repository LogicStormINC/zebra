"""Exact ownership, fresh fences and post-lock callbacks for the native owner."""
# ruff: noqa: F811 - imported pytest fixtures

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseLostError
from agent_storage.postgres.work_unit import borrow_work_unit, postgres_work_unit

from tests.agent_storage.test_coverage_evidence_operation import (  # noqa: F401
    acceptance,
    checkpoint,
    dsn,
    evidence,
    guard_io,
    metadata,
    model_cloud,
    operation,
    postgres_dsn,
    snapshot,
)
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE


@pytest.mark.parametrize("scope", ["deployment", "database", "namespace", "session", "request"])
def test_foreign_or_mixed_scope_refuses_before_upload(evidence, scope):
    env = evidence
    owner = operation(env)
    binding = env.binding
    if scope == "deployment":
        env.cloud.publisher._deployment = "foreign-deployment"
    elif scope == "database":
        env.cloud.publisher._database._dsn += " application_name=foreign-adapter"
    elif scope == "namespace":
        binding = binding.model_copy(update={"namespace": "foreign-tenant"})
    elif scope == "session":
        env.payload = env.payload.model_copy(update={"session_id": uuid4()})
    before, objects = snapshot(env), len(env.client.objects)
    with pytest.raises(ValueError):
        if scope == "request":
            request, payloads = acceptance(env)
            owner.commit_evidence(binding, request.model_copy(update={"namespace": "foreign"}),
                                  payloads, fence=env.fence)
        else:
            owner.publish_model_checkpoint(binding, env.receipt, env.payload, fence=env.fence)
    assert snapshot(env) == before and len(env.client.objects) == objects


def test_checkpoint_retained_metadata_is_full_and_immutable(evidence):
    env = evidence
    env.payload = env.payload.model_copy(update={
        "file_name": "private-original.json", "retained_until": env.binding.snapshot.expires_at,
    })
    checkpoint(env)
    record = metadata(env)
    assert record.reservation.file_name == "private-original.json"
    assert record.reservation.created_at == env.payload.created_at
    assert record.reservation.retained_until == env.payload.retained_until
    before = snapshot(env)
    env.payload = env.payload.model_copy(update={"file_name": "different.json"})
    with pytest.raises(ValueError, match="immutable publication conflicts"):
        checkpoint(env)
    assert snapshot(env) == before and metadata(env) == record


def test_crashed_upload_replacement_reuses_reservation_without_second_model_http(
    evidence, monkeypatch,
):
    env = evidence
    original = env.objects.put_if_absent

    def lost_upload(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("upload lost")

    before = snapshot(env)
    with monkeypatch.context() as patch:
        patch.setattr(env.objects, "put_if_absent", lost_upload)
        with pytest.raises(RuntimeError, match="upload lost"):
            checkpoint(env)
    staged = metadata(env)
    assert staged.lifecycle_revision == 0 and snapshot(env) == before
    original_fence = env.fence
    env.leases.release(env.session, fence=env.fence)
    env.fence = env.leases.acquire(
        env.session, owner_instance_id="evidence-replacement", ttl=timedelta(minutes=5),
    ).fence
    reserved = env.store.reserve_model_call(
        env.binding, env.receipt.reservation, fence=env.fence,
    )
    assert not reserved.invoke and reserved.receipt is None
    owner = operation(env)
    with pytest.raises((LeaseLostError, ValueError)):
        owner.publish_model_checkpoint(env.binding, env.receipt, env.payload, fence=original_fence)
    sequence, body = checkpoint(env, owner)
    finalized = metadata(env)
    assert finalized.reservation.created_at == staged.reservation.created_at
    assert finalized.reservation.idempotency_key == staged.reservation.idempotency_key
    assert body == env.payload.payload and len(env.requests) == 1
    assert checkpoint(env, owner) == (sequence, body)
    assert snapshot(env)[1] == [(1, 30, 0)]


@pytest.mark.parametrize("when", ["before_io", "after_lock"])
def test_stop_is_fresh_before_io_and_after_lock(evidence, monkeypatch, when):
    env = evidence

    def stop(connection=None):
        history = env.events.list_for_session(env.session)
        event = SessionEvent.create(
            session_id=env.session, sequence=history[-1].sequence + 1,
            event_type=EventType.SESSION_CANCELLED, actor=EventActor.SYSTEM,
            created_at=datetime.now(UTC), payload={"reason": "test STOP"},
        )
        env.events.append(event)

    before = snapshot(env)
    if when == "before_io":
        stop()
        before = snapshot(env)
    else:
        from agent_storage.postgres import coverage_evidence_operation as module

        lock = module.lock_run

        def stopped_after_lock(*args, **kwargs):
            row, version = lock(*args, **kwargs)
            stop(args[0])
            return row, version + 1

        monkeypatch.setattr(module, "lock_run", stopped_after_lock)
    with pytest.raises(ValueError):
        checkpoint(env)
    assert snapshot(env) == before


def test_owner_locks_run_once_and_observer_sees_staged_until_commit(evidence, monkeypatch):
    env = evidence
    from agent_storage.postgres import coverage_evidence_operation as module

    locked, observed = [], []
    lock = module.lock_run
    original = env.cloud.check_authority
    before = snapshot(env)

    def once(*args, **kwargs):
        locked.append(True)
        return lock(*args, **kwargs)

    def check():
        original()
        record = metadata(env)
        if (borrow_work_unit((env.dsn, NAMESPACE)) is not None
                and record is not None and record.lifecycle_status == "finalized"):
            with ThreadPoolExecutor(max_workers=1) as observer:
                assert observer.submit(snapshot, env).result() == before
                assert observer.submit(metadata, env).result().lifecycle_revision == 0
            observed.append(True)

    env.cloud.check_authority = check
    monkeypatch.setattr(module, "lock_run", once)
    checkpoint(env)
    assert locked == [True] and observed
    assert metadata(env).lifecycle_revision == 2


@pytest.mark.parametrize("alteration", ["store", "publisher", "deriver", "source", "borrowed"])
def test_altered_native_delegates_refuse(evidence, monkeypatch, alteration):
    env = evidence
    owner = operation(env)
    if alteration == "store":
        monkeypatch.setattr(env.store, "record_model_usage", lambda *a, **k: 1)
    elif alteration == "publisher":
        monkeypatch.setattr(env.cloud.publisher, "publish_batch", lambda *a, **k: ())
    elif alteration == "deriver":
        env.store._model_observation_deriver = lambda *args: None
    elif alteration == "source":
        monkeypatch.setattr(env.cloud, "_locked_proof_scope", lambda *a, **k: None)
    before = snapshot(env)
    if alteration == "borrowed":
        with postgres_work_unit(env.database), pytest.raises(ValueError, match="own completed"):
            checkpoint(env, owner)
    else:
        with pytest.raises(ValueError, match="altered|qualification"):
            checkpoint(env, owner)
    assert snapshot(env) == before and metadata(env) is None


def test_foreign_prior_object_is_not_read_as_evidence(evidence, monkeypatch):
    env = evidence
    checkpoint(env)
    request, payloads = acceptance(env)
    # Same physical store, unrelated namespace/session; the scoped query cannot enumerate it.
    foreign_id = ArtifactId(uuid4())
    forbidden = []
    original = env.objects.read_version_verified

    def read(expectation, version):
        if expectation.artifact_id == foreign_id:
            forbidden.append(True)
            raise AssertionError("foreign object read")
        return original(expectation, version)

    monkeypatch.setattr(env.objects, "read_version_verified", read)
    operation(env).commit_evidence(env.binding, request, payloads, fence=env.fence)
    assert not forbidden


def test_read_selector_and_locked_reader_kernel_alterations_refuse_before_io(
    evidence, monkeypatch,
):
    env = evidence
    owner = operation(env)
    from agent_storage.postgres import coverage_evidence_operation as module

    for target, method in (
        (type(env.store), "_commit_locked"), (type(env.store), "_settle_model_checkpoint_locked"),
        (module, "acceptance_evidence_ids"),
        (module.EvidenceOperationReads, "read_payload_verified_bounded"),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(target, method, lambda *args, **kwargs: None)
            with pytest.raises(ValueError, match="altered"):
                owner._qualify(env.binding)
        assert metadata(env) is None


def test_checkpoint_and_acceptance_kind_mime_refuse_before_staging(evidence):
    env = evidence
    owner = operation(env)
    before, objects = snapshot(env), len(env.client.objects)
    for updates in ({"kind": "coverage_results"}, {"mime_type": "application/octet-stream"}):
        with pytest.raises(ValueError, match="kind|MIME"):
            owner.publish_model_checkpoint(
                env.binding, env.receipt, env.payload.model_copy(update=updates), fence=env.fence,
            )
        assert metadata(env) is None and snapshot(env) == before
        assert len(env.client.objects) == objects
    request, payloads = acceptance(env)
    for index, updates in ((0, {"kind": "unknown"}), (1, {"mime_type": "text/plain"})):
        writes = tuple((identifier, payload.model_copy(update=updates) if i == index else payload)
                       for i, (identifier, payload) in enumerate(payloads))
        with pytest.raises(ValueError, match="kind|MIME"):
            owner.commit_evidence(env.binding, request, writes, fence=env.fence)
        assert all(metadata(env, identifier) is None for identifier, _ in writes)
        assert snapshot(env) == before and len(env.client.objects) == objects


def test_legacy_without_native_seals_refuses_before_io(evidence):
    env = evidence
    with env.database.connect() as connection:
        connection.execute(
            "DELETE FROM zebra_schema_migrations WHERE version=93",
        )
    before, objects = snapshot(env), len(env.client.objects)
    with pytest.raises(ValueError, match="prerequisites|legacy"):
        checkpoint(env)
    assert metadata(env) is None and snapshot(env) == before
    assert len(env.client.objects) == objects

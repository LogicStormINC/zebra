"""Coverage transaction regressions against disposable real PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_persistence import (
    CoverageRunBinding,
    coverage_manifest_bytes,
    coverage_result_bytes,
)
from agent_core.domain.coverage_validation import (
    AcceptedCoverageUnit,
    expected_units,
    manifest_digest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, TaskId
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.coverage import CoverageCommit
from agent_storage import (
    PostgresEventStore,
    PostgresLeaseStore,
    SQLiteArtifactPayloadStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres import coverage, coverage_transactions, task_admission
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.task_admission import save_task_binding

from tests.agent_core.test_coverage_contracts import contract, records, snapshot
from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed, dsn  # noqa: F401


@pytest.fixture
def env(dsn, tmp_path):  # noqa: F811 - imported pytest fixture
    session = _seed(dsn)
    frozen_host = _binding(str(session.session_id))
    host_data = frozen_host.model_dump()
    context = frozen_host.host_capability.host_context.model_copy(update={
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    })
    host_data["binding_revision"] = 2
    host_data["host_capability"].update({
        "host_context": context,
        "grant_digest": host_context_digest(context),
        "grant_expires_at": context.expires_at,
    })
    host_binding = TaskBindingSnapshot.model_validate(host_data)
    save_task_binding(dsn, deployment_namespace=NAMESPACE,
                      binding=host_binding,
                      expected_previous_revision=1)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    leases = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    lease = leases.acquire(session.session_id, owner_instance_id="coverage-worker",
                           ttl=timedelta(minutes=5))
    artifacts = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")
    items = records()
    body = coverage_manifest_bytes(items)
    artifact = artifacts.store_payload(ArtifactPayloadWrite(
        session_id=session.session_id, kind="coverage-manifest", mime_type="application/json",
        payload=body, created_at=datetime.now(UTC),
    ))
    frozen = snapshot(items).model_copy(update={
        "namespace": "tenant-a", "authority_revision": "permissions@7",
        "manifest_artifact_ref": artifact.uri, "as_of": datetime.now(UTC),
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    })
    binding = CoverageRunBinding(
        namespace="tenant-a", session_id=session.session_id, task_id=TaskId(session.session_id),
        run_id="run-1", contract=contract(), snapshot=frozen,
        manifest_artifact_digest=sha256(body).hexdigest(),
    )
    store = PostgresCoverageStore(dsn, deployment_namespace=NAMESPACE, artifacts=artifacts)
    return SimpleNamespace(dsn=dsn, session=session, binding=binding, store=store,
                           artifacts=artifacts, leases=leases, fence=lease.fence, items=items,
                           host_binding=host_binding)


def batch(env, *, keys=None, key="batch-1", session_id=None):
    keys = expected_units(env.binding.contract, env.items) if keys is None else keys
    results = tuple(AcceptedCoverageUnit(key=k, result_digest="b" * 64, outcome="clear")
                    for k in keys)
    body = coverage_result_bytes(results)
    artifact = env.artifacts.store_payload(ArtifactPayloadWrite(
        session_id=session_id or env.session.session_id, kind="coverage-results",
        mime_type="application/json", payload=body, created_at=datetime.now(UTC),
    ))
    return CoverageCommit(
        namespace=env.binding.namespace, session_id=env.session.session_id,
        task_id=env.binding.task_id, run_id=env.binding.run_id,
        snapshot_id=env.binding.snapshot.snapshot_id, contract_digest=env.binding.contract.digest,
        manifest_digest=env.binding.snapshot.manifest_digest, commit_key=key,
        result_artifact_ref=artifact.uri, result_artifact_digest=sha256(body).hexdigest(),
        results=results,
    )


def source_counts(env):
    with psycopg.connect(env.dsn) as connection:
        return connection.execute(
            "SELECT count(*) FROM session_events WHERE deployment_namespace=%s AND session_id=%s",
            (NAMESPACE, env.session.session_id),
        ).fetchone()[0]


def bind(env):
    return env.store.bind(env.binding, fence=env.fence)


def test_atomic_batch_and_retry_do_not_double_count(env):
    bind(env)
    request = batch(env)
    before = source_counts(env)
    receipt = env.store.commit(request, fence=env.fence)
    assert env.store.commit(request, fence=env.fence) == receipt
    reordered = request.model_copy(update={"results": request.results[::-1]})
    assert env.store.commit(reordered, fence=env.fence) == receipt
    assert source_counts(env) == before + 1
    assert env.store.counts("tenant-a", "run-1") == (4, 4)
    assert env.store.missing_units("tenant-a", "run-1", limit=10) == ()


def test_program_checks_do_not_store_model_membership_metadata(env):
    program = env.binding.contract.model_copy(update={
        "checks": tuple(check.model_copy(update={"kind": "program"})
                        for check in env.binding.contract.checks),
    })
    env.binding = env.binding.model_copy(update={
        "contract": program,
        "snapshot": env.binding.snapshot.model_copy(update={
            "contract_digest": program.digest,
            "manifest_digest": manifest_digest(program, env.items),
        }),
    })
    bind(env)
    with psycopg.connect(env.dsn) as connection:
        assert not connection.execute(
            "SELECT 1 FROM coverage_units WHERE record IS NOT NULL LIMIT 1"
        ).fetchall()
        assert not connection.execute("SELECT 1 FROM coverage_membership_seals").fetchall()
    env.store.commit(batch(env), fence=env.fence)
    assert env.store.counts("tenant-a", "run-1") == (4, 4)


def test_changed_retry_ref_is_not_accepted(env, monkeypatch):
    bind(env)
    request = batch(env)
    env.store.commit(request, fence=env.fence)
    altered = batch(env)  # Identical bytes but a different governed Artifact identity.
    monkeypatch.setattr(
        coverage, "verify_model_results",
        lambda *_, **__: pytest.fail("conflicting retry entered expensive MODEL proof"),
    )
    with pytest.raises(ValueError):
        env.store.commit(altered, fence=env.fence)
    assert env.store.counts("tenant-a", "run-1") == (4, 4)


@pytest.mark.parametrize("field,value", [
    ("namespace", "another-tenant"), ("snapshot_id", "another-snapshot"),
    ("contract_digest", "f" * 64), ("manifest_digest", "e" * 64),
])
def test_batch_scope_and_version_drift_fail_closed(env, field, value):
    bind(env)
    request = batch(env).model_copy(update={field: value})
    before = source_counts(env)
    with pytest.raises(ValueError):
        env.store.commit(request, fence=env.fence)
    assert source_counts(env) == before
    assert env.store.counts("tenant-a", "run-1") == (4, 0)


def test_exact_membership_and_overlapping_batch_rollback(env):
    bind(env)
    keys = expected_units(env.binding.contract, env.items)
    env.store.commit(batch(env, keys=(keys[0],)), fence=env.fence)
    before = source_counts(env)
    # The fresh unit must not persist when another unit in the same batch conflicts.
    with pytest.raises(ValueError):
        env.store.commit(batch(env, keys=(keys[1], keys[0]), key="overlap"), fence=env.fence)
    forged = keys[2].model_copy(update={"record_id": "invented"})
    with pytest.raises(ValueError):
        env.store.commit(batch(env, keys=(keys[1], forged), key="forged"), fence=env.fence)
    assert source_counts(env) == before
    assert env.store.counts("tenant-a", "run-1") == (4, 1)


def test_stale_fence_rejects_new_batch_and_retry(env):
    bind(env)
    request = batch(env)
    env.store.commit(request, fence=env.fence)
    env.leases.release(env.session.session_id, fence=env.fence)
    env.leases.acquire(env.session.session_id, owner_instance_id="replacement",
                       ttl=timedelta(minutes=5))
    with pytest.raises(LeaseLostError):
        env.store.commit(request, fence=env.fence)


def test_cancel_is_durable_and_blocks_late_results(env):
    bind(env)
    request = batch(env)
    env.store.cancel("tenant-a", "run-1", fence=env.fence)
    with pytest.raises(ValueError):
        env.store.commit(request, fence=env.fence)
    env.store.rebuild("tenant-a", "run-1")
    with pytest.raises(ValueError):
        env.store.commit(request, fence=env.fence)


def test_terminal_source_event_rejects_stale_projection(env):
    bind(env)
    events = PostgresEventStore(env.dsn, deployment_namespace=NAMESPACE)
    previous = events.list_for_session(env.session.session_id)[-1]
    events.append(SessionEvent.create(
        session_id=env.session.session_id, sequence=previous.sequence + 1,
        event_type=EventType.SESSION_CANCELLED, actor=EventActor.USER,
    ))
    with pytest.raises(ValueError):
        env.store.commit(batch(env), fence=env.fence)


def test_missing_artifact_cannot_count_or_rebuild(env):
    bind(env)
    request = batch(env)
    receipt = env.store.commit(request, fence=env.fence)
    env.artifacts.prune_payload(ArtifactId(UUID(request.result_artifact_ref.removeprefix("artifact://"))))
    before = source_counts(env)
    with pytest.raises((ValueError, FileNotFoundError)):
        env.store.rebuild("tenant-a", "run-1")
    assert source_counts(env) == before
    assert receipt.event_watermark > 0
    assert env.store.counts("tenant-a", "run-1") == (4, 4)  # Rebuild transaction rolled back.


def test_rebuild_from_events_recovers_exact_index_and_original_receipt(env):
    bind(env)
    request = batch(env)
    receipt = env.store.commit(request, fence=env.fence)
    before = source_counts(env)
    with psycopg.connect(env.dsn) as connection:
        connection.execute("DELETE FROM coverage_runs WHERE deployment_namespace=%s", (NAMESPACE,))
    env.store.rebuild("tenant-a", "run-1")
    assert env.store.counts("tenant-a", "run-1") == (4, 4)
    assert env.store.commit(request, fence=env.fence) == receipt
    assert source_counts(env) == before


def test_concurrent_retry_returns_single_receipt(env):
    bind(env)
    request = batch(env)
    before = source_counts(env)
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = tuple(pool.map(lambda _: env.store.commit(request, fence=env.fence), range(4)))
    assert len(set(r.event_watermark for r in receipts)) == 1
    assert source_counts(env) == before + 1


def test_bind_is_idempotent_and_cloud_scope_is_not_deployment_scope(env):
    first = bind(env)
    assert bind(env) == first
    assert env.store.counts("tenant-a", "run-1") == (4, 0)
    with pytest.raises(ValueError):
        env.store.counts("tenant-b", "run-1")
    bad = env.binding.model_copy(update={
        "run_id": "wrong-host",
        "snapshot": env.binding.snapshot.model_copy(update={"host_id": "wrong"}),
    })
    with pytest.raises(ValueError):
        env.store.bind(bad, fence=env.fence)


def test_result_artifact_from_another_session_is_rejected(env):
    bind(env)
    request = batch(env, session_id=uuid4())
    with pytest.raises(ValueError):
        env.store.commit(request, fence=env.fence)
    assert env.store.counts("tenant-a", "run-1") == (4, 0)


def test_expired_snapshot_does_not_create_run(env):
    bad = env.binding.model_copy(update={
        "snapshot": env.binding.snapshot.model_copy(update={
            "as_of": datetime.now(UTC) - timedelta(hours=2),
            "expires_at": datetime.now(UTC) - timedelta(hours=1),
        }),
    })
    before = source_counts(env)
    with pytest.raises(ValueError):
        env.store.bind(bad, fence=env.fence)
    assert source_counts(env) == before


def test_bound_manifest_cannot_be_replaced_with_different_check_version(env):
    bind(env)
    check = env.binding.contract.checks[0].model_copy(update={"version": "2"})
    updated = env.binding.contract.model_copy(update={"checks": (check,)})
    bad = env.binding.model_copy(update={"contract": updated})
    with pytest.raises(ValueError):
        env.store.bind(bad, fence=env.fence)


def test_missing_unit_query_is_bounded_and_exact(env):
    bind(env)
    keys = expected_units(env.binding.contract, env.items)
    env.store.commit(batch(env, keys=(keys[1],)), fence=env.fence)
    page = env.store.missing_units("tenant-a", "run-1", limit=2)
    missing = tuple(key for _, key in page)
    assert len(missing) == 2
    assert keys[1] not in missing
    assert set(missing) <= set(keys)
    next_page = env.store.missing_units("tenant-a", "run-1", limit=2, after_ordinal=page[-1][0])
    assert set(key for _, key in next_page).isdisjoint(missing)
    assert len(page) + len(next_page) == 3
    with pytest.raises(ValueError):
        env.store.missing_units("tenant-a", "run-1", limit=1001)


def test_crash_after_event_and_projection_rolls_back_entire_commit(env, monkeypatch):
    bind(env)
    request = batch(env)
    before = source_counts(env)
    original = coverage.project_batch

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic crash before transaction commit")

    with monkeypatch.context() as patch:
        patch.setattr(coverage, "project_batch", interrupted)
        with pytest.raises(RuntimeError, match="synthetic crash"):
            env.store.commit(request, fence=env.fence)
    assert source_counts(env) == before
    assert env.store.counts("tenant-a", "run-1") == (4, 0)
    with psycopg.connect(env.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM coverage_batches").fetchone()[0] == 0
    receipt = env.store.commit(request, fence=env.fence)
    with psycopg.connect(env.dsn) as connection:
        assert connection.execute(
            "SELECT source_watermark FROM coverage_continuations"
        ).fetchone()[0] == receipt.event_watermark


def test_written_but_uncommitted_result_artifact_does_not_count(env):
    bind(env)
    batch(env)
    assert env.store.counts("tenant-a", "run-1") == (4, 0)
    assert len(env.store.missing_units("tenant-a", "run-1")) == 4


def test_changed_host_binding_refuses_writes_but_can_still_cancel(env):
    bind(env)
    revised = env.host_binding.model_copy(update={"binding_revision": 3})
    save_task_binding(env.dsn, deployment_namespace=NAMESPACE, binding=revised,
                      expected_previous_revision=2)
    with pytest.raises(ValueError, match="binding changed"):
        env.store.commit(batch(env), fence=env.fence)
    env.store.cancel("tenant-a", "run-1", fence=env.fence)


def test_cancel_does_not_require_available_manifest(env):
    bind(env)
    artifact_id = ArtifactId(UUID(env.binding.snapshot.manifest_artifact_ref[11:]))
    env.artifacts.prune_payload(artifact_id)
    assert env.store.cancel("tenant-a", "run-1", fence=env.fence) > 0


def test_accepted_event_records_fence_and_replay_survives_new_worker(env):
    bind(env)
    receipt = env.store.commit(batch(env), fence=env.fence)
    source = PostgresEventStore(env.dsn, deployment_namespace=NAMESPACE).list_for_session(
        env.session.session_id
    )[-1]
    assert source.payload["fence"] == env.fence.model_dump(mode="json")
    env.leases.release(env.session.session_id, fence=env.fence)
    env.leases.acquire(env.session.session_id, owner_instance_id="replacement",
                       ttl=timedelta(minutes=5))
    assert env.store.rebuild("tenant-a", "run-1") == receipt.event_watermark


def test_replay_refuses_missing_historical_fence_without_losing_index(env):
    bind(env)
    env.store.commit(batch(env), fence=env.fence)
    with psycopg.connect(env.dsn) as connection:
        # Corruption injection in this disposable test schema only; retain
        # production immutable-event triggers introduced by later migrations.
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            "UPDATE session_events SET payload=payload-'fence' "
            "WHERE event_type='coverage_batch_accepted'"
        )
    with pytest.raises(ValueError):
        env.store.rebuild("tenant-a", "run-1")
    assert env.store.counts("tenant-a", "run-1") == (4, 4)


def test_lease_expiry_after_unit_updates_rolls_back_before_event(env, monkeypatch):
    bind(env)
    request = batch(env)
    before = source_counts(env)
    env.leases.heartbeat(env.session.session_id, fence=env.fence,
                         ttl=timedelta(milliseconds=400), checkpoint=0)
    original = coverage.accept_units

    def delayed(connection, *args):
        original(connection, *args)
        connection.execute("SELECT pg_sleep(0.5)")

    monkeypatch.setattr(coverage, "accept_units", delayed)
    with pytest.raises(LeaseLostError):
        env.store.commit(request, fence=env.fence)
    assert source_counts(env) == before
    assert env.store.counts("tenant-a", "run-1") == (4, 0)


def test_snapshot_expiry_refuses_progress_without_preventing_cancel(env):
    env.binding = env.binding.model_copy(update={
        "snapshot": env.binding.snapshot.model_copy(update={
            "expires_at": datetime.now(UTC) + timedelta(milliseconds=500),
        }),
    })
    bind(env)
    with psycopg.connect(env.dsn) as connection:
        connection.execute("SELECT pg_sleep(0.6)")
    with pytest.raises(ValueError, match="snapshot has expired"):
        env.store.commit(batch(env), fence=env.fence)
    assert env.store.cancel("tenant-a", "run-1", fence=env.fence) > 0


def test_binding_renewal_serializes_after_final_validation(env, monkeypatch):
    bind(env)
    request = batch(env)
    validated = Event()
    release = Event()
    renewal_attempted = Event()
    renewal_pid = []
    original_append = coverage_transactions.append_event_in_transaction
    original_lock = task_admission._lock_task

    def pause_after_validation(*args):
        validated.set()
        assert release.wait(5), "test did not release the coverage transaction"
        return original_append(*args)

    def track_renewal_lock(connection, *args):
        renewal_pid.append(connection.info.backend_pid)
        renewal_attempted.set()
        return original_lock(connection, *args)

    monkeypatch.setattr(
        coverage_transactions, "append_event_in_transaction", pause_after_validation
    )
    monkeypatch.setattr(task_admission, "_lock_task", track_renewal_lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = pool.submit(env.store.commit, request, fence=env.fence)
        assert validated.wait(5)
        revised = env.host_binding.model_copy(update={"binding_revision": 3})
        renewal = pool.submit(save_task_binding, env.dsn, deployment_namespace=NAMESPACE,
                              binding=revised, expected_previous_revision=2)
        try:
            assert renewal_attempted.wait(5)
            deadline = monotonic() + 2
            blocked = None
            with psycopg.connect(env.dsn) as connection:
                while monotonic() < deadline:
                    blocked = connection.execute(
                        "SELECT 1 FROM pg_locks WHERE pid=%s AND NOT granted",
                        (renewal_pid[0],),
                    ).fetchone()
                    if blocked:
                        break
                    sleep(0.01)
                assert blocked, "renewal must wait on the coverage Task boundary"
        finally:
            release.set()
        assert accepted.result(timeout=5).event_watermark > 0
        assert renewal.result(timeout=5) == revised.binding_digest
    with pytest.raises(ValueError, match="binding changed"):
        env.store.commit(request, fence=env.fence)
    env.store.cancel("tenant-a", "run-1", fence=env.fence)


def test_bind_index_work_cannot_outlive_lease_before_commit(env, monkeypatch):
    before = source_counts(env)
    original = coverage.seed_run
    env.leases.heartbeat(env.session.session_id, fence=env.fence,
                         ttl=timedelta(milliseconds=400), checkpoint=0)

    def delayed(connection, *args):
        result = original(connection, *args)
        connection.execute("SELECT pg_sleep(0.5)")
        return result

    monkeypatch.setattr(coverage, "seed_run", delayed)
    with pytest.raises(LeaseLostError):
        bind(env)
    assert source_counts(env) == before
    with psycopg.connect(env.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM coverage_runs").fetchone()[0] == 0

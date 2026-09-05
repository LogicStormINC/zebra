"""Real PostgreSQL instance identity/fence accounting; no container engine IO."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import (
    ExecutionAuthorityResolutionRequest,
    ExecutionAuthoritySnapshot,
)
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_storage import PostgresLeaseStore
from agent_storage.postgres.runtime_instances import PostgresRuntimeInstances
from psycopg.types.json import Jsonb

from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_execution import _authority
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff, _prepare
from tests.agent_storage.test_postgres_lease_clock import _wait, _wait_locked, _worker_dsn

dsn = _dsn_fixture
postgres_dsn = _pg_fixture
SCOPE = OpaqueAuthorityScope(authority_issuer="https://trench.example", namespace_id="tenant-a")


def _setup(dsn, *, event=None):
    event = _prepare(dsn) if event is None else event
    lease = _handoff(dsn, event).lease
    snapshot = _authority(SCOPE).resolve_for_attempt(
        ExecutionAuthorityResolutionRequest(
            session_id=event.session_id,
            attempt_number=1,
            scope=SCOPE,
            validated_at=datetime.now(UTC),
        )
    )
    _store(dsn).append(
        SessionEvent.create(
            session_id=event.session_id,
            sequence=4,
            actor=EventActor.SYSTEM,
            event_type=EventType.EXECUTION_AUTHORITY_RESOLVED,
            payload=snapshot.model_dump(mode="json"),
        )
    )
    return lease


def _instances(dsn, lease, **kwargs):
    return PostgresRuntimeInstances(
        dsn,
        deployment_namespace=kwargs.pop("namespace", NAMESPACE),
        scope=kwargs.pop("scope", SCOPE),
        lease=lease,
        engine_identity=kwargs.pop("engine", "a" * 64),
        workspace_ref=kwargs.pop(
            "workspace", _binding("test").host_capability.host_context.workspace_ref
        ),
    )


def _rows(dsn):
    with psycopg.connect(dsn) as connection:
        return connection.execute(
            "SELECT instance_id,status,container_id FROM runtime_instances ORDER BY created_at"
        ).fetchall()


def test_two_instances_are_distinct_and_exact_removal_is_idempotent(dsn):
    lease = _setup(dsn)
    instances = _instances(dsn, lease)
    first, second = str(uuid4()), str(uuid4())
    for instance, container in ((first, "a" * 64), (second, "b" * 64)):
        instances.reserve(instance, str(lease.session_id), "digest")
        instances.created(instance, container)
        instances.authorize(instance, container)
    instances.removed(first, "a" * 64)
    instances.removed(first, "a" * 64)
    assert [row[1] for row in _rows(dsn)] == ["removed", "created"]


@pytest.mark.parametrize("change", ["scope", "workspace", "namespace", "engine"])
def test_wrong_identity_never_mutates_existing_instance(dsn, change):
    lease = _setup(dsn)
    original = _instances(dsn, lease)
    instance = str(uuid4())
    original.reserve(instance, str(lease.session_id), "digest")
    kwargs = (
        {"scope": SCOPE.model_copy(update={"namespace_id": "victim"})}
        if change == "scope"
        else {change: "b" * 64 if change == "engine" else "victim"}
    )
    impostor = _instances(dsn, lease, **kwargs)
    before = _rows(dsn)
    with pytest.raises(ValueError):
        impostor.created(instance, "a" * 64)
    assert _rows(dsn) == before


def test_cancel_then_late_create_records_obligation_but_never_authorizes_start(dsn):
    lease = _setup(dsn)
    instances = _instances(dsn, lease)
    instance = str(uuid4())
    instances.reserve(instance, str(lease.session_id), "digest")
    store = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    store.release(lease.session_id, fence=lease.fence)
    instances.created(instance, "a" * 64)
    with pytest.raises(LeaseLostError):
        instances.authorize(instance, "a" * 64)
    assert _rows(dsn)[0][1] == "created"
    instances.removed(instance, "a" * 64)
    assert _rows(dsn)[0][1] == "removed"


def test_successor_cannot_settle_predecessor_instance_or_use_predecessor_fence(dsn):
    lease = _setup(dsn)
    old = _instances(dsn, lease)
    instance = str(uuid4())
    old.reserve(instance, str(lease.session_id), "digest")
    old.created(instance, "a" * 64)
    store = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    store.release(lease.session_id, fence=lease.fence)
    successor = store.acquire(
        lease.session_id, owner_instance_id="worker", ttl=timedelta(seconds=30)
    )
    with pytest.raises(ValueError):
        _instances(dsn, successor).removed(instance, "a" * 64)
    with pytest.raises(LeaseLostError):
        old.authorize(instance, "a" * 64)
    assert _rows(dsn)[0][1] == "created"


def test_unsettled_create_cannot_be_removed_after_empty_scan(dsn):
    lease = _setup(dsn)
    instances = _instances(dsn, lease)
    instance = str(uuid4())
    instances.reserve(instance, str(lease.session_id), "digest")
    with pytest.raises(ValueError, match="unsettled"):
        instances.removed(instance, "a" * 64)
    assert _rows(dsn)[0][1:] == ("provisioning", None)


def test_omitting_existing_host_workspace_fails_closed_without_reservation(dsn):
    lease = _setup(dsn)
    with pytest.raises(ValueError, match="workspace"):
        _instances(dsn, lease, workspace=None).reserve(
            str(uuid4()), str(lease.session_id), "digest"
        )
    assert _rows(dsn) == []


def test_generic_cloud_binding_without_host_context_keeps_opaque_authority(dsn):
    lease = _setup(dsn)
    with psycopg.connect(dsn) as connection:
        raw = connection.execute("SELECT snapshot_json FROM task_binding_snapshots").fetchone()[0]
        raw["host_capability"]["host_context"] = None
        binding = TaskBindingSnapshot.model_validate(raw)
        connection.execute(
            "UPDATE task_binding_snapshots SET snapshot_json=%s,binding_digest=%s",
            (Jsonb(binding.model_dump(mode="json")), binding.binding_digest),
        )
    instances = _instances(dsn, lease, workspace=None)
    instance = str(uuid4())
    instances.reserve(instance, str(lease.session_id), "digest")
    instances.created(instance, "a" * 64)
    instances.authorize(instance, "a" * 64)
    assert _rows(dsn)[0][1] == "created"


def test_generic_cloud_without_task_binding_uses_canonical_opaque_authority(dsn):
    lease = _setup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("DELETE FROM task_binding_snapshots")
    instances = _instances(dsn, lease, workspace=None)
    instance = str(uuid4())
    instances.reserve(instance, str(lease.session_id), "digest")
    instances.created(instance, "a" * 64)
    instances.authorize(instance, "a" * 64)


def test_missing_canonical_authority_never_reserves_an_instance(dsn):
    lease = _setup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "DELETE FROM session_events WHERE event_type='execution_authority_resolved'"
        )
    with pytest.raises(ValueError, match="canonical execution authority"):
        _instances(dsn, lease).reserve(str(uuid4()), str(lease.session_id), "digest")
    assert _rows(dsn) == []


@pytest.mark.parametrize("operation", ["reserve", "authorize"])
def test_stream_lock_wait_cannot_use_expired_lease(dsn, operation):
    lease = _setup(dsn)
    instance = str(uuid4())
    if operation == "authorize":
        existing = _instances(dsn, lease)
        existing.reserve(instance, str(lease.session_id), "digest")
        existing.created(instance, "a" * 64)
    name = f"runtime-wait-{uuid4()}"
    instances = _instances(_worker_dsn(dsn, name), lease)
    with psycopg.connect(dsn, autocommit=True) as observer:
        observer.execute(
            "UPDATE worker_leases SET expires_at=clock_timestamp()+interval '1 second'"
        )
        with psycopg.connect(dsn) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
            blocker.execute("SELECT * FROM session_streams FOR UPDATE").fetchall()
            future = (
                pool.submit(instances.reserve, instance, str(lease.session_id), "digest")
                if (operation == "reserve")
                else pool.submit(instances.authorize, instance, "a" * 64)
            )
            try:
                _wait_locked(observer, name)
                _wait(observer, "SELECT clock_timestamp()>expires_at FROM worker_leases", ())
            finally:
                blocker.commit()
            with pytest.raises(LeaseLostError):
                future.result(timeout=5)
    assert len(_rows(dsn)) == (0 if operation == "reserve" else 1)


@pytest.mark.parametrize("container", ["alias", "abc123", "A" * 64, "g" * 64])
def test_container_names_and_short_ids_never_become_exact_targets(dsn, container):
    lease = _setup(dsn)
    instances = _instances(dsn, lease)
    instance = str(uuid4())
    instances.reserve(instance, str(lease.session_id), "digest")
    with pytest.raises(ValueError, match="container identity"):
        instances.created(instance, container)
    assert _rows(dsn)[0][1:] == ("provisioning", None)


@pytest.mark.parametrize("expired", ["lease", "authority"])
def test_instance_row_wait_rechecks_lease_and_authority_after_lock(dsn, expired):
    lease = _setup(dsn)
    instance = str(uuid4())
    original = _instances(dsn, lease)
    original.reserve(instance, str(lease.session_id), "digest")
    original.created(instance, "a" * 64)
    name = f"instance-wait-{uuid4()}"
    instances = _instances(_worker_dsn(dsn, name), lease)
    before = _rows(dsn)
    with psycopg.connect(dsn, autocommit=True) as observer:
        deadline = observer.execute("SELECT clock_timestamp()+interval '1 second'").fetchone()[0]
        if expired == "lease":
            observer.execute("UPDATE worker_leases SET expires_at=%s", (deadline,))
        else:
            payload = observer.execute(
                "SELECT payload FROM session_events WHERE event_type='execution_authority_resolved'"
            ).fetchone()[0]
            payload.update(expires_at=deadline.isoformat(), snapshot_digest=None)
            snapshot = ExecutionAuthoritySnapshot.model_validate(payload)
            observer.execute(
                "UPDATE session_events SET payload=%s "
                "WHERE event_type='execution_authority_resolved'",
                (Jsonb(snapshot.model_dump(mode="json")),),
            )
        with psycopg.connect(dsn) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
            blocker.execute("SELECT * FROM runtime_instances FOR UPDATE").fetchall()
            future = pool.submit(instances.authorize, instance, "a" * 64)
            try:
                _wait_locked(observer, name)
                _wait(observer, "SELECT clock_timestamp()>%s", (deadline,))
            finally:
                blocker.commit()
            error = LeaseLostError if expired == "lease" else ValueError
            with pytest.raises(error):
                future.result(timeout=5)
    assert _rows(dsn) == before

"""Atomic Task admission tests against real PostgreSQL (v25)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
)
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import (
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from psycopg import connect


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    deployment_namespace = f"admission-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=deployment_namespace)
    return deployment_namespace


def _request(
    *,
    binding: TaskBindingSnapshot | None = None,
    idempotency: IdempotencyRecord | None = None,
) -> TaskAdmissionRequest:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Admission test",
            user_input="hello",
            workspace_root="/tmp/admission-test",
        )
    )
    workspace = rebuild_workspace(list(bootstrap.events))
    return TaskAdmissionRequest(
        events=tuple(bootstrap.events),
        session=bootstrap.session,
        workspace=workspace,
        binding=binding,
        idempotency=idempotency,
    )


def _binding(task_id: str) -> TaskBindingSnapshot:
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="a" * 64,
        capability_profile_ref="profile/default@1",
        capabilities=capability_set(["evidence.read"]),
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id="host-a",
        authority_issuer="https://host-a.example.com",
        namespace_id="tenant-a",
        grant_digest="c" * 64,
        connector_id="host-a-main",
        connector_profile_revision=1,
        connector_profile_digest="d" * 64,
        manifest_digest="b" * 64,
        capabilities=capability_set(["evidence.read"]),
        resource_binding_digest="e" * 64,
        bound_at=datetime.now(UTC),
    )
    return TaskBindingSnapshot(
        task_id=task_id,
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest="f" * 64,
        effective_capabilities=capability_set(["evidence.read"]),
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )


def _receipt(dsn: str, namespace: str, key: str) -> IdempotencyRecord:
    return IdempotencyRecord(
        action="task.admission.test",
        idempotency_key=key,
        request_hash="r" * 64,
        status_code=201,
        response_body={"task": key},
        created_at=datetime.now(UTC),
    )


def _count(dsn: str, namespace: str, table: str, column: str, value: str) -> int:
    with connect(dsn) as connection:
        row = connection.execute(
            f"SELECT count(*) FROM {table} "
            f"WHERE deployment_namespace = %s AND {column} = %s",
            (namespace, value),
        ).fetchone()
    return int(row[0])


def test_admission_persists_every_object_atomically(
    namespace: str, postgres_dsn: str
) -> None:
    transaction = PostgresTaskAdmissionTransaction(
        postgres_dsn, deployment_namespace=namespace
    )
    request = _request()
    receipt = transaction.admit(request)
    session_id = str(receipt.session_id)
    assert receipt.event_count == len(request.events)
    assert _count(postgres_dsn, namespace, "session_events", "session_id", session_id) == len(
        request.events
    )
    assert _count(postgres_dsn, namespace, "session_projections", "session_id", session_id) == 1
    assert _count(postgres_dsn, namespace, "agent_tasks", "task_id", str(receipt.task_id)) == 1


def test_admission_with_binding_persists_snapshot(
    namespace: str, postgres_dsn: str
) -> None:
    transaction = PostgresTaskAdmissionTransaction(
        postgres_dsn, deployment_namespace=namespace
    )
    request = _request()
    binding = _binding(str(request.events[0].session_id))
    receipt = transaction.admit(
        TaskAdmissionRequest(
            events=request.events,
            session=request.session,
            workspace=request.workspace,
            binding=binding,
        )
    )
    assert receipt.binding_digest == binding.binding_digest
    assert (
        _count(
            postgres_dsn,
            namespace,
            "task_binding_snapshots",
            "task_id",
            str(receipt.task_id),
        )
        == 1
    )


def test_idempotent_replay_short_circuits(namespace: str, postgres_dsn: str) -> None:
    transaction = PostgresTaskAdmissionTransaction(
        postgres_dsn, deployment_namespace=namespace
    )
    key = f"key-{uuid4()}"
    receipt_record = _receipt(postgres_dsn, namespace, str(key))
    base = _request()
    first = transaction.admit(
        TaskAdmissionRequest(
            events=base.events,
            session=base.session,
            workspace=base.workspace,
            idempotency=receipt_record,
        )
    )
    assert not first.idempotent_replay
    replay = transaction.admit(_request(idempotency=receipt_record))
    assert replay.idempotent_replay
    assert replay.event_count == 0
    assert _count(
        postgres_dsn, namespace, "session_events", "session_id", str(first.session_id)
    ) == len(base.events)
    assert _count(
        postgres_dsn, namespace, "session_events", "session_id", str(replay.session_id)
    ) == 0


def test_injected_failure_leaves_no_partial_task(namespace: str, postgres_dsn: str) -> None:
    transaction = PostgresTaskAdmissionTransaction(
        postgres_dsn, deployment_namespace=namespace
    )
    # first, one fully admitted Task with a binding at revision 1
    established = _request()
    established_task = str(established.events[0].session_id)
    transaction.admit(
        TaskAdmissionRequest(
            events=established.events,
            session=established.session,
            workspace=established.workspace,
            binding=_binding(established_task),
        )
    )
    # second admission: fresh Session/Events (all inserts succeed), but its
    # binding reuses the first task_id at the same revision — the LAST insert
    # violates the task_binding_snapshots primary key mid-transaction
    fresh = _request()
    colliding_binding = _binding(established_task)
    try:
        transaction.admit(
            TaskAdmissionRequest(
                events=fresh.events,
                session=fresh.session,
                workspace=fresh.workspace,
                binding=colliding_binding,
            )
        )
    except Exception:
        pass
    else:
        raise AssertionError("colliding binding must fail the admission mid-transaction")
    fresh_session = str(fresh.events[0].session_id)
    assert _count(postgres_dsn, namespace, "session_events", "session_id", fresh_session) == 0
    assert _count(postgres_dsn, namespace, "session_projections", "session_id", fresh_session) == 0
    assert (
        _count(postgres_dsn, namespace, "task_binding_snapshots", "task_id", established_task)
        == 1
    )
    assert (
        _count(postgres_dsn, namespace, "session_events", "session_id", established_task)
        == len(established.events)
    )


def test_migration_v25_table_exists(postgres_dsn: str) -> None:
    with connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_name = 'task_binding_snapshots'
            """
        ).fetchone()
    assert int(row[0]) == 1


def test_request_validation_rejects_mismatched_binding() -> None:
    request = _request()
    foreign = _binding(str(uuid4()))
    with pytest.raises(ValueError, match="binding must reference"):
        TaskAdmissionRequest(
            events=request.events,
            session=request.session,
            workspace=request.workspace,
            binding=foreign,
        ).validate()

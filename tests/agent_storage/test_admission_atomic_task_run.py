"""Task + first RUN + native wakeups are visible only after the original commit."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace

import pytest
from agent_storage.postgres.admission_atomic_surface import (
    AtomicSurfaceAborted,
    atomic_surface_transaction,
    observe_atomic_termination,
    start_atomic_surface,
)
from zebra_agent_api.session_payloads import parse_create_session_payload
from zebra_agent_api.session_queue import create_queued_session

from tests.agent_storage.test_admission_atomic_surface import result, setup
from tests.agent_storage.test_admission_atomic_task import counts
from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated

isolated_migration_dsn = _isolated
PROTOCOL = "atomic-task-run/1"


def effects(store):
    from uuid import uuid4

    from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant

    from tests.agent_storage.test_command_wakeup import _binding

    context = _binding(str(uuid4())).host_capability.host_context
    verified = VerifiedHostGrant(
        context, context.grant_id, JwtAlgorithm.RS256, context.origin, "user-a"
    )
    db = store._database
    parsed = parse_create_session_payload(
        {"title": "queued", "prompt": "hello", "workspace": "/tmp/atomic-run", "execute": True}
    )
    response = create_queued_session(
        SimpleNamespace(artifact_payloads=object()),
        parsed,
        admission_dsn=db._dsn,
        admission_namespace=db.deployment_namespace,
        initial_run_id="run:exact-owned",
        host_context=context,
        verified_host_grant=verified,
    )
    assert response.status_code == 201 and response.body["status"] == "queued"
    return response


def command_counts(store):
    with store._database.connect() as c:
        return [
            c.execute(
                f"SELECT count(*) AS n FROM {table} WHERE deployment_namespace=%s",
                (store._database.deployment_namespace,),
            ).fetchone()["n"]
            for table in ("session_command_pending", "broker_outbox")
        ]


def enable(store):
    with store._database.connect() as c:
        c.execute(
            "INSERT INTO command_wakeup_rollouts(deployment_namespace,admission_enabled) "
            "VALUES(%s,true)",
            (store._database.deployment_namespace,),
        )


def observe(store, op, write):
    return observe_atomic_termination(store, op, "a" * 64, write=write, protocol=PROTOCOL)


def test_uncommitted_run_not_discoverable_stop_rolls_back_everything(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    enable(store)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    ready, release = Event(), Event()

    def run():
        with pytest.raises(AtomicSurfaceAborted):
            with atomic_surface_transaction(store, op, "a" * 64):
                effects(store)
                assert command_counts(store) == [1, 1]
                result(store, op)
                ready.set()
                assert release.wait(5)

    with ThreadPoolExecutor(1) as pool:
        task = pool.submit(run)
        assert ready.wait(5)
        assert counts(store) == [0] * 5 and command_counts(store) == [0, 0]
        assert observe(store, op, True)["state"] == "pending"
        release.set()
        task.result()
    assert counts(store) == [0] * 5 and command_counts(store) == [0, 0]
    assert observe(store, op, False)["state"] == "terminated"
    assert not start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)


def test_committed_run_has_exact_persisted_identity_never_noncommit(
    isolated_migration_dsn, monkeypatch,
):
    from agent_storage.postgres import task_admission

    append = task_admission.append_task_bootstrap_in_transaction
    statements = []

    def observe_bootstrap(connection, namespace, events):
        class Probe:
            def execute(self, statement, params):
                statements.append(statement)
                return connection.execute(statement, params)

        return append(Probe(), namespace, events)

    monkeypatch.setattr(task_admission, "append_task_bootstrap_in_transaction", observe_bootstrap)
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    enable(store)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    with atomic_surface_transaction(store, op, "a" * 64):
        effects(store)
        result(store, op)
    assert len(statements) == 2
    assert "INSERT INTO session_streams" in statements[0]
    assert "INSERT INTO session_events" in statements[1]
    assert command_counts(store) == [1, 1]
    with store._database.connect() as c:
        event = c.execute(
            "SELECT payload FROM session_events WHERE deployment_namespace=%s "
            "AND event_type='session_command_accepted'",
            (store._database.deployment_namespace,),
        ).fetchone()
        assert event["payload"]["payload"]["run_id"] == "run:exact-owned"
        task = c.execute(
            "SELECT event_position_state,event_index_repair_cursor,event_index_repair_highwater "
            "FROM agent_tasks WHERE deployment_namespace=%s",
            (store._database.deployment_namespace,),
        ).fetchone()
        assert task == {
            "event_position_state": "ready",
            "event_index_repair_cursor": -1,
            "event_index_repair_highwater": -1,
        }
    assert observe(store, op, True)["state"] == "committed"
    assert (
        observe_atomic_termination(store, op, "a" * 64, write=True, protocol="atomic-task/1")[
            "state"
        ]
        == "unsupported"
    )


def test_atomic_initial_run_indexes_before_wakeup_and_rolls_back_on_rejection(
    isolated_migration_dsn, monkeypatch
):
    from agent_storage.postgres import task_admission

    store, op = setup(isolated_migration_dsn, PROTOCOL)
    enable(store)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    wake = task_admission.record_command_wakeup_in_transaction
    rebuild = task_admission.rebuild_task_in_transaction
    indexed = []
    root_member_reads = []
    task_locks = []

    def observe_rebuild(connection, namespace, session_id, **kwargs):
        class AdmissionConnection:
            def __getattr__(self, name):
                return getattr(connection, name)

            def transaction(self):
                pytest.fail("atomic Task rebuild must use its existing admission transaction")

            @contextmanager
            def cursor(self, **options):
                with connection.cursor(**options) as cursor:
                    class RebuildCursor:
                        def execute(self, statement, params):
                            if "pg_advisory_xact_lock(hashtextextended(%s,61))" in statement:
                                task_locks.append(params)
                            if ("SELECT created_at FROM session_projections" in statement
                                or "FROM execution_segments WHERE" in statement
                                or "LEFT JOIN execution_segments AS member" in statement):
                                root_member_reads.append(statement)
                            return cursor.execute(statement, params)

                    yield RebuildCursor()

        task = rebuild(AdmissionConnection(), namespace, session_id, **kwargs)
        indexed.append(session_id)
        return task

    def reject(connection, namespace, event, *, is_new_admission):
        assert indexed == [event.session_id]
        assert len(root_member_reads) == 1
        assert len(task_locks) == 1
        wake(connection, namespace, event, is_new_admission=is_new_admission)
        raise AtomicSurfaceAborted("controlled wakeup rollback")

    monkeypatch.setattr(task_admission, "rebuild_task_in_transaction", observe_rebuild)
    monkeypatch.setattr(task_admission, "record_command_wakeup_in_transaction", reject)
    with pytest.raises(AtomicSurfaceAborted, match="controlled wakeup rollback"):
        with atomic_surface_transaction(store, op, "a" * 64):
            effects(store)
    assert counts(store) == [0] * 5 and command_counts(store) == [0, 0]


@pytest.mark.parametrize("before_commit", [True, False])
def test_atomic_first_run_reconciles_original_on_commit_disconnect(
    isolated_migration_dsn, before_commit
):
    from agent_storage.postgres.idempotency import PostgresIdempotencyStore
    from psycopg import OperationalError

    from tests.api.test_artifact_download_deadline import lost_commit_reply

    store, op = setup(isolated_migration_dsn, PROTOCOL)
    enable(store)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    with lost_commit_reply(isolated_migration_dsn, before_commit=before_commit) as (
        proxy_dsn,
        interrupted,
        _,
    ):
        through_proxy = PostgresIdempotencyStore(
            proxy_dsn, deployment_namespace=store._database.deployment_namespace
        )
        with pytest.raises(OperationalError):
            with atomic_surface_transaction(through_proxy, op, "a" * 64):
                effects(through_proxy)
                result(through_proxy, op)
        assert interrupted.is_set()
    if before_commit:
        assert observe(store, op, False)["state"] == "unresolved"
        assert counts(store) == [0] * 5 and command_counts(store) == [0, 0]
        assert observe(store, op, True)["state"] == "terminated"
    else:
        assert observe(store, op, False)["state"] == "committed"
        assert command_counts(store) == [1, 1]

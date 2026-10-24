"""Real Task rows and sealed-result transaction; absence is never standalone proof."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from agent_storage.postgres.admission_atomic_surface import (
    AtomicSurfaceAborted,
    atomic_surface_transaction,
    observe_atomic_termination,
    start_atomic_surface,
)
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction

from tests.agent_storage.test_admission_atomic_surface import result, setup
from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated
from tests.agent_storage.test_postgres_task_admission import _binding, _request

isolated_migration_dsn = _isolated
PROTOCOL = "atomic-task/1"


def observe(store, op, write):
    return observe_atomic_termination(store, op, "a" * 64, write=write, protocol=PROTOCOL)


def task_effects(store):
    from dataclasses import replace

    request = _request()
    request = replace(request, binding=_binding(str(request.session.session_id)))
    db = store._database
    return PostgresTaskAdmissionTransaction(
        db._dsn, deployment_namespace=db.deployment_namespace
    ).admit(request)


def counts(store):
    with store._database.connect() as c:
        return [
            c.execute(
                f"SELECT count(*) AS n FROM {table} WHERE deployment_namespace=%s",
                (store._database.deployment_namespace,),
            ).fetchone()["n"]
            for table in (
                "session_events",
                "session_projections",
                "workspace_projections",
                "agent_tasks",
                "task_binding_snapshots",
            )
        ]


def test_task_stop_during_real_sql_pending_then_full_rollback(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    ready, release = Event(), Event()

    def run():
        with pytest.raises(AtomicSurfaceAborted):
            with atomic_surface_transaction(store, op, "a" * 64):
                task_effects(store)
                assert all(v > 0 for v in counts(store))
                result(store, op)
                ready.set()
                assert release.wait(5)

    with ThreadPoolExecutor(1) as pool:
        execution = pool.submit(run)
        assert ready.wait(5)
        assert counts(store) == [0] * 5
        assert observe(store, op, True)["state"] == "pending"
        release.set()
        execution.result()
    assert counts(store) == [0] * 5
    assert observe(store, op, False)["state"] == "terminated"
    assert not start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    # Surface protocol cannot upgrade/observe a Task proof.
    assert observe_atomic_termination(store, op, "a" * 64, write=False)["state"] == "unsupported"


def test_task_commit_first_never_noncommit(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    with atomic_surface_transaction(store, op, "a" * 64):
        task_effects(store)
        result(store, op)
    assert all(v > 0 for v in counts(store))
    assert observe(store, op, True)["state"] == "committed"


def test_task_error_rolls_back_but_requires_explicit_stop(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    with pytest.raises(TimeoutError):
        with atomic_surface_transaction(store, op, "a" * 64):
            task_effects(store)
            raise TimeoutError("owned receipt failure")
    assert counts(store) == [0] * 5
    assert observe(store, op, False)["state"] == "unresolved"
    assert observe(store, op, True)["state"] == "terminated"

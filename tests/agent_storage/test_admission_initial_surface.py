"""Exact-owner authority reads and Task/Surface/RUN share the original commit."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import pytest
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres.admission_atomic_surface import (
    AtomicSurfaceAborted,
    atomic_surface_transaction,
    observe_atomic_termination,
    start_atomic_surface,
)
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from agent_storage.postgres.task_admission import load_task_binding

from tests.agent_storage.test_admission_atomic_surface import (
    counts as surface_counts,
)
from tests.agent_storage.test_admission_atomic_surface import (
    effects as surface_effects,
)
from tests.agent_storage.test_admission_atomic_surface import (
    result,
    setup,
)
from tests.agent_storage.test_admission_atomic_task import counts as task_counts
from tests.agent_storage.test_admission_atomic_task_run import (
    command_counts,
    enable,
)
from tests.agent_storage.test_admission_atomic_task_run import (
    effects as task_effects,
)
from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated

isolated_migration_dsn = _isolated
PROTOCOL = "atomic-task-run-surface/1"


def binding(store, task, namespace=None):
    return load_task_binding(
        store._database._dsn,
        deployment_namespace=namespace or store._database.deployment_namespace,
        task_id=TaskId(UUID(task)),
    )


def test_owned_authority_read_sees_uncommitted_task_ordinary_reader_does_not(
    isolated_migration_dsn,
):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    enable(store)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    with atomic_surface_transaction(store, op, "a" * 64):
        task = str(task_effects(store).body["session_id"])
        tasks = PostgresAgentTaskStore(
            store._database._dsn, deployment_namespace=store._database.deployment_namespace
        )
        assert tasks.get_task(TaskId(UUID(task))) is not None
        assert binding(store, task) is not None
        # Independent proof/header readers retain their existing isolation contract.
        with store._database.connect_task_io() as independent:
            assert (
                independent.execute(
                    "SELECT count(*) AS n FROM agent_tasks WHERE deployment_namespace=%s",
                    (store._database.deployment_namespace,),
                ).fetchone()["n"]
                == 0
            )
        assert binding(store, task, "other-namespace") is None
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(binding, store, task).result() is None
            assert pool.submit(tasks.get_task, TaskId(UUID(task))).result() is None
        surface_effects(store)
        result(store, op)
    assert binding(store, task) is not None
    assert command_counts(store) == [1, 1]
    assert surface_counts(store) == [1, 1, 1]
    proof = observe_atomic_termination(store, op, "a" * 64, write=True, protocol=PROTOCOL)
    assert proof["state"] == "committed"


def test_task_surface_run_and_result_all_rollback_when_stop_wins(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    enable(store)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    ready, release = Event(), Event()

    def dispatch():
        with pytest.raises(AtomicSurfaceAborted):
            with atomic_surface_transaction(store, op, "a" * 64):
                task_effects(store)
                surface_effects(store)
                result(store, op)
                ready.set()
                assert release.wait(5)

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(dispatch)
        assert ready.wait(5)
        assert task_counts(store) == [0] * 5
        assert surface_counts(store) == [0, 0, 0]
        assert command_counts(store) == [0, 0]
        proof = observe_atomic_termination(store, op, "a" * 64, write=True, protocol=PROTOCOL)
        assert proof["state"] == "pending"
        release.set()
        future.result()
    assert task_counts(store) == [0] * 5
    assert surface_counts(store) == [0, 0, 0]
    assert command_counts(store) == [0, 0]
    assert (
        observe_atomic_termination(store, op, "a" * 64, write=False, protocol=PROTOCOL)["state"]
        == "terminated"
    )

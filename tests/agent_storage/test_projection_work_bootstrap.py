"""Explicit resumable Task-head discovery, including lower-ID concurrent arrivals."""

import threading
from uuid import UUID

import pytest
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

from tests.agent_storage.test_task_projection_work import queue as _queue_fixture
from tests.agent_storage.test_task_projection_work import scratch as _scratch_fixture

queue, scratch = _queue_fixture, _scratch_fixture


def insert_task(queue, number, namespace=None, connection=None):
    namespace = queue.namespace if namespace is None else namespace
    statement = (
        "INSERT INTO agent_tasks(task_id,namespace,next_event_sequence,event_position_state) "
        "VALUES (?,?,0,'ready')"
        if queue.backend == "sqlite"
        else "INSERT INTO agent_tasks(task_id,deployment_namespace,"
        "next_event_sequence,event_position_state) "
        "VALUES (?,?,0,'ready')"
    )
    if connection is not None:
        queue.execute(connection, statement, (str(UUID(int=number)), namespace))
    else:
        with queue.connect() as connection:
            queue.execute(connection, statement, (str(UUID(int=number)), namespace))


def test_existing_no_append_limit_restart_versions_namespace_and_inert_close(queue):
    for n in range(10, 50):
        insert_task(queue, n)
    insert_task(queue, 999, "other")
    queue.install()
    store = queue.store()
    with pytest.raises(CheckpointNotReady):
        store.bootstrap_projection_work()
    store.enable_projection_work()
    assert store.read_projection_work_repairs() == ()  # Enable does not scan/adopt.
    assert not store.bootstrap_projection_work()
    assert len(store.read_projection_work_repairs()) == 32
    # Cursor resumes at the next Task ID, not a prefix. New lower ID arrives without any Event.
    insert_task(queue, 1)
    assert any(r.scope.task_id == UUID(int=1) for r in queue.store().read_projection_work_repairs())
    assert queue.store().bootstrap_projection_work()
    with queue.connect() as connection:
        route_count = queue.execute(
            connection,
            "SELECT COUNT(*) AS n FROM task_projection_work_routes "
            "WHERE deployment_namespace=? AND projector_version='ag-ui-v1'",
            (queue.namespace,),
        ).fetchone()["n"]
    assert route_count == 42
    assert queue.store().bootstrap_projection_work()
    assert store.read_pending_projection_work() == ()  # Discovery is not checkpoint initialization.
    other_version = queue.store(version="ag-ui-v2")
    other_version.enable_projection_work()
    assert not other_version.bootstrap_projection_work(limit=7)
    assert len(other_version.read_projection_work_repairs()) == 7
    other_namespace = queue.store(namespace="other")
    other_namespace.enable_projection_work()
    assert other_namespace.bootstrap_projection_work()
    assert [r.scope.task_id for r in other_namespace.read_projection_work_repairs()] == [
        UUID(int=999)
    ]
    for invalid in (0, 33, True, -1):
        with pytest.raises(ValueError):
            store.bootstrap_projection_work(limit=invalid)


def test_completed_cursor_restart_does_not_rescan_tasks(queue):
    queue.install()
    store = queue.store()
    store.enable_projection_work()
    assert store.bootstrap_projection_work()
    # A SELECT-denying authorizer proves the terminal bootstrap path only reads its config row.
    if queue.backend == "sqlite":
        import sqlite3
        from contextlib import contextmanager

        @contextmanager
        def connect(**kwargs):
            with store._connect(**kwargs) as connection:
                connection.set_authorizer(
                    lambda action, table, *_: sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_READ and table == "agent_tasks"
                    else sqlite3.SQLITE_OK
                )
                yield connection

        resumed = queue.store()
        resumed._connect = connect
        assert resumed.bootstrap_projection_work()
    # New lower-ID Task after completed discovery is independently enqueued by the native hook.
    insert_task(queue, 0)
    assert any(r.scope.task_id == UUID(int=0) for r in queue.store().read_projection_work_repairs())


def test_first_enable_and_uncommitted_old_task_serialized(queue):
    queue.install()
    store = queue.store()
    if queue.backend == "sqlite":
        insert_task(queue, 0)
        store.enable_projection_work()
    else:
        errors, started = [], threading.Event()
        with queue.connect() as connection:
            insert_task(queue, 0, connection=connection)

            def enable():
                started.set()
                try:
                    store.enable_projection_work()
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=enable)
            thread.start()
            assert started.wait(timeout=1)
            connection.commit()  # Source INSERT hook holds namespace config lock until this commit.
        thread.join(timeout=2)
        assert not thread.is_alive() and not errors
    assert store.bootstrap_projection_work()
    assert any(r.scope.task_id == UUID(int=0) for r in store.read_projection_work_repairs())

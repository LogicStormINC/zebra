"""Healthy projection maintenance must not lock the canonical append route."""

from contextlib import contextmanager
from threading import Barrier, Event, Thread

import pytest

from tests.agent_storage.projection_work_test_support import QueueFixture
from tests.agent_storage.test_postgres_scalar_task_replay_headers import scratch as _scratch_fixture
from tests.agent_storage.test_task_projection_work import active

scratch = _scratch_fixture


def test_healthy_repair_does_not_wait_for_writer_route_lock(scratch, tmp_path):
    queue = QueueFixture("postgres", tmp_path, scratch)
    store = active(queue)
    queue.append(0)
    before = queue.work_rows()
    with queue.connect() as writer:
        writer.execute("SELECT 1 FROM task_projection_work_routes FOR UPDATE")
        result = store.repair_projection_work(queue.task)
    assert not result.needs_repair and result.after_sequence == 0
    assert queue.work_rows() == before


def test_slow_healthy_repair_exit_cannot_block_canonical_append(scratch, tmp_path):
    queue = QueueFixture("postgres", tmp_path, scratch)
    store = active(queue)
    queue.append(0)
    entered, release = Event(), Event()
    errors = []
    original = store._connect

    @contextmanager
    def slow_exit(**kwargs):
        with original(**kwargs) as connection:
            yield connection
            entered.set()
            assert release.wait(3), "test did not release maintenance"

    store._connect = slow_exit

    def repair():
        try:
            store.repair_projection_work(queue.task)
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=repair)
    thread.start()
    try:
        assert entered.wait(3)
        # The production task writer uses a 50ms lock budget. Do not relax it.
        original_connect = queue.connect

        @contextmanager
        def writer_connection():
            with original_connect() as connection:
                connection.execute("SET LOCAL lock_timeout='50ms'")
                yield connection

        queue.connect = writer_connection
        queue.append(1, body='{"safe":true}')
    finally:
        release.set()
        thread.join(4)
    assert not thread.is_alive() and not errors
    assert store.read_pending_projection_work()[0].requested_through == 1


@pytest.mark.parametrize("slow_sequence", [0, 1])
def test_dirty_repair_releases_each_header_before_next_source_read(
    scratch, tmp_path, monkeypatch, slow_sequence,
):
    """A delayed second header must not hold the first header's route/work locks."""
    from agent_storage.postgres.projection_work_io import _WorkConnection

    queue = QueueFixture("postgres", tmp_path, scratch)
    queue.append(0)
    queue.append(1)
    store = active(queue)
    entered, release = Event(), Event()
    errors = []
    original = _WorkConnection.execute

    def delayed_read(connection, statement, params=None):
        if "AS header_bytes" in statement and params[-1] == slow_sequence:
            entered.set()
            assert release.wait(3), "writer did not release repair"
        return original(connection, statement, params)

    monkeypatch.setattr(_WorkConnection, "execute", delayed_read)

    def repair():
        try:
            store.repair_projection_work(queue.task)
        except Exception as exc:
            # The bounded page may expire during this injected source stall.
            from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
            if not isinstance(exc, CheckpointNotReady):
                errors.append(exc)

    thread = Thread(target=repair)
    thread.start()
    try:
        assert entered.wait(3)
        with queue.connect() as reader:
            route = reader.execute(
                "SELECT observed_through FROM task_projection_work_routes"
            ).fetchone()
            prefix = route["observed_through"]
        original_connect = queue.connect

        @contextmanager
        def writer_connection():
            with original_connect() as connection:
                connection.execute("SET LOCAL lock_timeout='50ms'")
                yield connection

        queue.connect = writer_connection
        queue.append(2)
        assert prefix == slow_sequence - 1, "completed prefix must already be durable"
    finally:
        release.set()
        thread.join(4)
    assert not thread.is_alive() and not errors
    monkeypatch.setattr(_WorkConnection, "execute", original)
    for _ in range(10):
        result = store.repair_projection_work(queue.task)
        if not result.needs_repair:
            break
    assert not result.needs_repair and result.after_sequence == 2
    rows = queue.work_rows()
    assert [(r["anchor_sequence"], r["requested_through"], r["closed_through"]) for r in rows] == [
        (0, 0, 0), (1, 1, 1), (2, 2, None),
    ]


def test_two_repairs_racing_on_same_header_do_not_double_advance(scratch, tmp_path, monkeypatch):
    from agent_storage.postgres.projection_work_io import _WorkConnection

    queue = QueueFixture("postgres", tmp_path, scratch)
    queue.append(0)
    store = active(queue)
    barrier, errors = Barrier(2), []
    original = _WorkConnection.execute

    def simultaneous_read(connection, statement, params=None):
        if "AS header_bytes" in statement:
            barrier.wait(timeout=3)
        return original(connection, statement, params)

    monkeypatch.setattr(_WorkConnection, "execute", simultaneous_read)

    def repair():
        try:
            store.repair_projection_work(queue.task, limit=1)
        except Exception as exc:
            errors.append(exc)

    threads = [Thread(target=repair) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(4)
    assert not errors and not any(thread.is_alive() for thread in threads)
    with queue.connect() as connection:
        route = connection.execute("SELECT * FROM task_projection_work_routes").fetchone()
        assert route["observed_through"] == route["wanted_through"] == 0
        assert route["needs_repair"] == 0
    assert len(queue.work_rows()) == 1
    assert queue.work_rows()[0]["requested_through"] == 0


def test_completed_header_restores_cleanup_budget_before_next_roundtrip(
    scratch, tmp_path, monkeypatch,
):
    from agent_storage.postgres.projection_work_io import _WorkConnection

    queue = QueueFixture("postgres", tmp_path, scratch)
    queue.append(0)
    store = active(queue)
    original = _WorkConnection.execute
    budgets = []

    def observe_budget(connection, statement, params=None):
        result = original(connection, statement, params)
        if statement == "DO %s":
            row = connection.connection.execute(
                "SELECT current_setting('statement_timeout')::interval AS budget"
            ).fetchone()
            budgets.append(row["budget"].total_seconds())
        return result

    monkeypatch.setattr(_WorkConnection, "execute", observe_budget)
    assert not store.repair_projection_work(queue.task, limit=1).needs_repair
    assert len(budgets) == 1 and budgets[0] > 0.2


def test_commit_preparation_cancel_retains_prior_header_and_rolls_back_current(
    scratch, tmp_path, monkeypatch,
):
    from agent_storage.postgres.projection_work_io import _WorkConnection

    queue = QueueFixture("postgres", tmp_path, scratch)
    queue.append(0)
    queue.append(1)
    store = active(queue)
    original, headers = _WorkConnection.execute, []
    cancelled = False

    def cancel_second_commit(connection, statement, params=None):
        nonlocal cancelled
        if statement == "DO %s":
            headers.append(1)
        if statement == "COMMIT" and len(headers) == 2 and not cancelled:
            cancelled = True
            return original(connection, "DO $$BEGIN RAISE EXCEPTION 'cancel cleanup' "
                "USING ERRCODE='57014'; END$$")
        return original(connection, statement, params)

    monkeypatch.setattr(_WorkConnection, "execute", cancel_second_commit)
    first = store.repair_projection_work(queue.task)
    assert first.after_sequence == 0 and first.needs_repair
    rows = queue.work_rows()
    assert len(rows) == 1 and rows[0]["closed_through"] is None
    monkeypatch.setattr(_WorkConnection, "execute", original)
    assert not store.repair_projection_work(queue.task).needs_repair
    assert [(r["requested_through"], r["closed_through"]) for r in queue.work_rows()] == [
        (0, 0), (1, None),
    ]

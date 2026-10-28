"""Healthy projection maintenance must not lock the canonical append route."""

from contextlib import contextmanager
from threading import Event, Thread

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

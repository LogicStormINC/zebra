"""Barrier-driven process-lifetime and native source-wiring regressions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Event, Thread
from threading import enumerate as live_threads
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.agent_tasks import TaskEvent
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_integrations.ag_ui.binding_resolution import (
    BINDING_VERSION,
    BindingResolutionPending,
    advance_binding_resolution,
)
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.checkpoint_plan import AG_UI_CHECKPOINT_VERSION
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage import SQLiteAgentTaskStore, SQLiteProjectionStore
from zebra_agent_worker import build_worker_loop_service
from zebra_agent_worker.ag_ui_projection_work import AgUiProjectionWorkService
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.worker_loop_service import WorkerLoopService

from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import (
    Ticks,
    _append,
    _attach,
    _command,
    _consumer,
    _deny_source_bodies,
    _forbid_history,
    _native,
    _no_thread,
    _page_spy,
    _prefix_sources,
    _restore,
    _service,
    _source_offset,
    _task,
    assert_cold_cursor_oracle,
    orphan_sources,
    prepare_source_projections,
)
from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import (
    native_source as _native_source_fixture,
)
from tests.agent_integrations.test_ag_ui_projection import _event
from tests.agent_storage.test_projection_work_native import failure_count
from tests.agent_storage.test_projection_work_native import native_dsn as native_dsn
from tests.worker.test_loop import _settings

native_source = _native_source_fixture


def test_concurrent_start_and_repeated_close_have_one_live_worker():
    consumer = Ticks()
    service = _service(consumer)
    barrier = Barrier(3)
    errors = []

    def start():
        try:
            barrier.wait(timeout=2)
            service.start()
        except BaseException as exc:
            errors.append(exc)

    starters = [Thread(target=start) for _ in range(2)]
    try:
        for thread in starters:
            thread.start()
        barrier.wait(timeout=2)
        for thread in starters:
            thread.join(timeout=2)
        assert not errors and consumer.tick.wait(timeout=2)
        thread = service._thread
        service.start()
        assert service._thread is thread
        assert consumer.enables == 1
    finally:
        service.close()
        service.close()
        for thread in starters:
            thread.join(timeout=2)
    _no_thread(service)


def test_close_before_start_and_two_lifetimes_leave_no_threads():
    before = {thread.ident for thread in live_threads()}
    consumer = Ticks()
    service = _service(consumer)
    service.close()
    try:
        for _ in range(2):
            consumer.tick.clear()
            service.start()
            assert consumer.tick.wait(timeout=2)
            service.close()
            service.close()
            _no_thread(service)
        assert consumer.enables == 2
    finally:
        service.close()
    assert not [
        thread
        for thread in live_threads()
        if thread.name == "ag-ui-projection" and thread.ident not in before
    ]


def test_native_consumer_keeps_projecting_while_worker_execution_is_blocked(tmp_path, monkeypatch):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    sessions = SQLiteProjectionStore(tasks._database.database_path)
    session = sessions.get_session(task.active_segment_id)
    sessions.save_session(session.model_copy(update={"status": SessionStatus.READY}))
    entered, release, projected = Event(), Event(), Event()
    complete = queue.complete_projection_work
    results, errors = [], []

    def ack(work, *, expected_through):
        accepted = complete(work, expected_through=expected_through)
        if accepted and expected_through == 2:
            projected.set()
        return accepted

    monkeypatch.setattr(queue, "complete_projection_work", ack)

    class BlockingExecution:
        def execute_session(self, session_id, **kwargs):
            assert session_id == task.active_segment_id
            _append(
                events,
                task,
                1,
                EventType.MODEL_RESPONSE_DELTA,
                {"model_call_id": "blocking", "content_delta": "during provider wait"},
            )
            _append(
                events,
                task,
                2,
                EventType.MODEL_RESPONSE_RECEIVED,
                {"model_call_id": "blocking", "assistant_message": "during provider wait"},
            )
            entered.set()
            assert release.wait(timeout=4), "execution test barrier was not released"

    consumer = AgUiCheckpointConsumer(tasks, queue, namespace="local")
    service = _service(consumer)
    worker = WorkerLoopService(sessions, BlockingExecution(), projection_work=service)

    def run():
        try:
            results.append(worker.run(worker_id="blocked-worker", max_cycles=1))
        except BaseException as exc:
            errors.append(exc)

    execution = Thread(target=run)
    try:
        execution.start()
        assert entered.wait(timeout=2)
        assert projected.wait(timeout=2), "background projection waited for execution to return"
        assert execution.is_alive() and not release.is_set()
    finally:
        release.set()
        execution.join(timeout=4)
        service.close()
    assert not execution.is_alive() and not errors
    assert results[0].executed_session_ids == (str(task.active_segment_id),)
    _no_thread(service)


def test_blocking_enable_never_blocks_admitted_execution_or_leaks_thread(tmp_path):
    entered, release, executed = Event(), Event(), Event()
    consumer = Ticks()

    def enable():
        entered.set()
        assert release.wait(timeout=4)

    consumer.enable_projection_work = enable
    service = _service(consumer)

    class Commands:
        def consume_once(self, **kwargs):
            executed.set()
            return SimpleNamespace(session_id="admitted", status="executed", command_kind="run")

    worker = WorkerLoopService(
        SQLiteProjectionStore(tmp_path / "enable.sqlite"),
        object(),
        command_consumer=Commands(),
        scan_ready_sessions=False,
        projection_work=service,
    )
    errors = []

    def poll():
        try:
            worker.poll_once(worker_id="admitted")
        except BaseException as exc:
            errors.append(exc)

    caller = Thread(target=poll)
    try:
        caller.start()
        assert entered.wait(timeout=2)
        assert executed.wait(timeout=1), "synchronous maintenance enable blocked admitted command"
    finally:
        release.set()
        caller.join(timeout=4)
        worker.drain()
    assert not caller.is_alive() and not errors
    _no_thread(service)


def test_enable_failure_does_not_replace_original_execution_error(tmp_path, caplog):
    consumer = Ticks()
    consumer.enable_error = RuntimeError("private maintenance error")
    service = _service(consumer)
    original = RuntimeError("original execution failure")
    executed = []

    class Commands:
        def consume_once(self, **kwargs):
            executed.append(True)
            assert consumer.enabled.wait(timeout=2)
            raise original

    worker = WorkerLoopService(
        SQLiteProjectionStore(tmp_path / "errors.sqlite"),
        object(),
        command_consumer=Commands(),
        scan_ready_sessions=False,
        projection_work=service,
    )
    try:
        with pytest.raises(RuntimeError) as caught:
            worker.run(worker_id="original", max_cycles=1)
        assert caught.value is original and executed == [True]
        assert "private maintenance error" not in caplog.text
    finally:
        worker.drain()
    _no_thread(service)


def test_poll_exception_does_not_kill_background_ticks_and_close_interrupts_backoff(caplog):
    consumer = Ticks()
    consumer.poll_error = RuntimeError("private failed poll")
    service = _service(consumer)
    try:
        service.start()
        assert consumer.tick.wait(timeout=2), "background thread died after one poll exception"
        assert consumer.calls >= 2
        assert "RuntimeError" in caplog.text and "private failed poll" not in caplog.text
    finally:
        service.close()
    _no_thread(service)


def test_projection_failure_and_bad_execution_do_not_starve_other_ready_task(tmp_path):
    tasks, _, _ = _native(tmp_path)
    first, second = _task(tasks, ordinal=1), _task(tasks, ordinal=2)
    sessions = SQLiteProjectionStore(tasks._database.database_path)
    for task in (first, second):
        session = sessions.get_session(task.active_segment_id)
        sessions.save_session(session.model_copy(update={"status": SessionStatus.READY}))
    consumer = Ticks()
    consumer.enable_error = RuntimeError("maintenance failed")
    service = _service(consumer)
    executed = []

    class Execution:
        def execute_session(self, session_id, **kwargs):
            assert consumer.enabled.wait(timeout=2)
            executed.append(session_id)
            if session_id == first.active_segment_id:
                raise WorkerExecutionError("known task-specific failure")

    worker = WorkerLoopService(sessions, Execution(), projection_work=service)
    try:
        result = worker.run(worker_id="independent", batch_size=2, max_cycles=1)
        assert set(executed) == {first.active_segment_id, second.active_segment_id}
        assert result.skipped_session_ids == (str(first.active_segment_id),)
        assert result.executed_session_ids == (str(second.active_segment_id),)
    finally:
        worker.drain()
    _no_thread(service)


def test_production_worker_builder_composes_checkpoint_background_without_manual_preparation(
    tmp_path,
):
    path = tmp_path / "builder.sqlite"
    worker = build_worker_loop_service(
        database_path=path, settings=_settings(path), sleep=lambda _: None
    )
    service = worker._projection_work
    assert service is not None, "production Worker builder silently disabled checkpoint consumer"
    tasks = service.consumer.tasks
    queue = service.consumer.work
    queue.enable_projection_work()
    task = _task(tasks)
    _command(worker._execution_service._event_store, task)
    completed = Event()
    original = queue.complete_projection_work

    def ack(work, *, expected_through):
        result = original(work, expected_through=expected_through)
        if result:
            completed.set()
        return result

    queue.complete_projection_work = ack
    try:
        worker.maintenance_once(worker_id="builder", batch_size=1, lease_ttl_seconds=30)
        assert completed.wait(timeout=2)
        assert not queue.read_pending_projection_work()
    finally:
        worker.drain()
    _no_thread(service)


def test_production_runner_discovers_old_native_task_without_new_append(tmp_path, monkeypatch):
    path = tmp_path / "old-task.sqlite"
    first = build_worker_loop_service(database_path=path, settings=_settings(path))
    service = first._projection_work
    assert service is not None
    tasks, queue = service.consumer.tasks, service.consumer.work
    task = _task(tasks)
    source = _command(first._execution_service._event_store, task)
    assert not queue.read_pending_projection_work()
    assert not queue.read_projection_work_repairs(), "fixture already seeded a wake"
    scope = ProjectionScope("local", task.task_id, source.event.event_id, AG_UI_CHECKPOINT_VERSION)
    assert tasks.read_checkpoint_head(scope).through_sequence == -1
    first.drain()  # Never start/enable its background consumer.

    # A cold production builder must discover pre-existing metadata. No fake
    # repair queue, explicit backfill, new source append, or checkpoint prepare.
    worker = build_worker_loop_service(database_path=path, settings=_settings(path))
    service = worker._projection_work
    assert service is not None
    completed = Event()
    queue = service.consumer.work
    complete = queue.complete_projection_work

    def ack(work, *, expected_through):
        result = complete(work, expected_through=expected_through)
        if result and work.scope == scope:
            completed.set()
        return result

    monkeypatch.setattr(queue, "complete_projection_work", ack)
    _forbid_history(service.consumer.tasks, monkeypatch)
    try:
        worker.maintenance_once(worker_id="old-task", batch_size=1, lease_ttl_seconds=30)
        assert completed.wait(timeout=2), (
            "production runner never discovered old Task without append"
        )
        assert service.consumer.tasks.read_checkpoint_head(scope).through_sequence == 0
        assert service.consumer.tasks.read_run_header(task.task_id, "run").highwater == 0
    finally:
        worker.drain()
    _no_thread(service)


def test_native_binding_ledger_metadata_only_cold_batches_expose_all_pending_reasons(
    tmp_path, monkeypatch
):
    # Direct production ledger API proof, deliberately separate from the
    # consumer/runner wiring checks: no test-built ProjectionTransition.
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    child = _attach(tasks, task.task_id, task.active_segment_id)
    for sequence in range(257):
        events.append(
            _event(
                child,
                sequence,
                EventType.SESSION_HANDOFF_RECEIVED,
                {"handoff_id": str(uuid4()), "parent_session_id": str(task.active_segment_id)},
            )
        )
    work = queue.read_pending_projection_work()[0]
    run = tasks.read_run_header(task.task_id, "run")
    page = tasks.read_event_page(task.task_id, -1, through_sequence=run.highwater)
    identity = AgUiRunIdentity(
        session_id=task.active_segment_id, thread_id=str(task.task_id), run_id="run"
    )
    ledger = ProjectionScope("local", task.task_id, work.scope.anchor_event_id, BINDING_VERSION)
    reads, frontiers = [], [-1]
    for _ in range(8):
        restored = SQLiteAgentTaskStore(tasks._database.database_path)
        _forbid_history(restored, monkeypatch)
        connect = restored._database.connect

        @contextmanager
        def guarded(connect=connect):
            connection = connect()
            _deny_source_bodies(connection, reads)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

        monkeypatch.setattr(restored._database, "connect", guarded)
        head = advance_binding_resolution(restored, run, work.scope, limit=256)
        assert head.scope == ledger and 0 < head.through_sequence - frontiers[-1] <= 256
        frontiers.append(head.through_sequence)
        with pytest.raises(BindingResolutionPending) as pending:
            build_projection_page_plan(restored, page, run, work.scope, identity)
        assert pending.value.resolved_through == head.through_sequence
        assert pending.value.required_through == run.highwater
        assert pending.value.reason == (
            "admission" if head.through_sequence == run.highwater else "resolution"
        )
        if head.through_sequence == run.highwater:
            break
    assert frontiers[-1] == 257 and len(frontiers) > 3
    assert reads == [] and queue.read_projection_work_problem(work.scope) is None
    assert restored.read_checkpoint_head(work.scope).through_sequence == -1
    assert restored.read_checkpoint_head(ledger).through_sequence == 257


@pytest.mark.parametrize("finish", ["late_pair", "closure"])
def test_native_257_orphan_ledger_survives_cold_consumer_and_preserves_oracle(
    native_source, monkeypatch, finish
):
    tasks, events, queue = native_source
    task = _task(tasks)
    offset = _source_offset(tasks)
    sources = orphan_sources(tasks, events, task)
    child = _attach(tasks, task.task_id, task.active_segment_id)
    sources.extend(_prefix_sources(tasks, task, after=len(sources) - 1))
    child_offset = offset

    def append(segment, sequence, kind, payload):
        sequence += 2 * offset if segment == task.active_segment_id else child_offset
        if offset and kind is EventType.SESSION_HANDOFF_RECEIVED:
            payload = {**payload, "root_session_id": str(task.task_id), "stage_index": 1}
        source = _event(segment, sequence, kind, payload)
        events.append(source)
        sources.append(TaskEvent(task.task_id, len(sources), segment, sequence, source))

    if offset:
        append(child, 0, EventType.TASK_PREPARED, {"title": "Child", "user_input": "Inspect"})
    child_offset += offset
    append(
        child,
        0,
        EventType.MODEL_RESPONSE_DELTA,
        {"model_call_id": "orphan-prefix", "content_delta": "prefix"},
    )
    for sequence in range(1, 258):
        append(
            child,
            sequence,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(uuid4()), "parent_session_id": str(task.active_segment_id)},
        )
    work = queue.read_pending_projection_work()[0]
    ledger = ProjectionScope("local", task.task_id, work.scope.anchor_event_id, BINDING_VERSION)
    _forbid_history(tasks, monkeypatch)
    _page_spy(tasks, monkeypatch)
    consumer = AgUiCheckpointConsumer(tasks, queue, namespace="local")
    run = tasks.read_run_header(task.task_id, work.run_id, through_sequence=work.requested_through)
    page = tasks.read_event_page(task.task_id, -1, through_sequence=run.highwater)
    identity = AgUiRunIdentity(
        session_id=task.active_segment_id, thread_id=str(task.task_id), run_id=work.run_id)
    with pytest.raises(BindingResolutionPending) as pending:
        build_projection_page_plan(tasks, page, run, work.scope, identity)
    assert pending.value.reason == "budget"
    assert (
        pending.value.resolved_through == -1 and pending.value.required_through == 258 + 4 * offset
    )
    assert consumer.materialize_once(work) is False
    for _ in range(16):
        consumer.poll_once(budget_seconds=2)
    assert tasks.read_checkpoint_head(ledger).through_sequence == 258 + 4 * offset, (
        "consumer did not advance ledger"
    )
    assert tasks.read_checkpoint_head(work.scope).through_sequence == -1
    problem = queue.read_projection_work_problem(work.scope)
    assert problem is not None and problem.code == "not_ready"
    assert problem.attempts == 0 and problem.retry_at is None

    restored = _restore(tasks)
    _forbid_history(restored, monkeypatch)
    _page_spy(restored, monkeypatch)
    assert restored.read_checkpoint_head(ledger).through_sequence == 258 + 4 * offset
    assert queue.read_projection_work_problem(work.scope) == problem
    consumer = AgUiCheckpointConsumer(restored, queue, namespace="local")
    if finish == "late_pair":
        handoff = str(uuid4())
        append(
            task.active_segment_id,
            1,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": handoff, "target_session_id": str(child)},
        )
        append(child, 258, EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": handoff, "parent_session_id": str(task.active_segment_id)},
        )
        append(child, 259, EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "orphan-prefix", "assistant_message": "prefix"},
        )
        target = 261 + 4 * offset
    else:
        append(
            task.active_segment_id,
            1,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "run", "payload": {"run_id": "next"}},
        )
        target = 258 + 4 * offset
        closed = next(row for row in queue.read_pending_projection_work() if row.run_id == "run")
        assert closed.closed_through == target
        assert restored.read_run_header(task.task_id, "run").stop == target + 1
        handoff = str(uuid4())
        append(
            task.active_segment_id,
            2,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": handoff, "target_session_id": str(child)},
        )
        append(child, 258, EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": handoff, "parent_session_id": str(task.active_segment_id)},
        )
        append(child, 259, EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "orphan-prefix", "assistant_message": "prefix"},
        )
        assert (
            next(row for row in queue.read_pending_projection_work() if row.run_id == "run")
            == closed
        )
    assert queue.read_projection_work_problem(work.scope) is None, "canonical wake kept stale wait"
    assert not queue.defer_projection_work(work, problem_code="not_ready"), (
        "stale wait reblocked wake"
    )
    for _ in range(16):
        consumer.poll_once(budget_seconds=2)
    assert restored.read_checkpoint_head(work.scope).through_sequence == target
    assert queue.read_projection_work_problem(work.scope) is None
    assert not any(row.run_id == "run" for row in queue.read_pending_projection_work())
    prepare_source_projections(tasks, sources)
    observer = AgUiCheckpointObserver(restored, namespace="local")
    snapshot = observer.snapshot(task.task_id, identity)
    assert snapshot.through == target
    after, actual = snapshot.run.start - 1, []
    while (page := observer.read_page(snapshot, after)) is not None:
        assert len(page.events) <= 256 and page.byte_count <= 1_048_576
        actual.extend(observer.iter_page_frames(snapshot, page, identity))
        after = page.next_sequence
    assert actual == list(AgUiTaskProjector().project_task_events(sources, identity))
    assert_cold_cursor_oracle(tasks, task, identity, sources, monkeypatch)


@pytest.mark.parametrize("prior_failures", [0, 7])
def test_native_admission_wake_is_not_lost_to_previous_temporary_failure_budget(
    native_source, monkeypatch, prior_failures
):
    tasks, events, queue = native_source
    task = _task(tasks)
    _command(events, task)
    offset = _source_offset(tasks)
    child = _attach(tasks, task.task_id, task.active_segment_id)
    events.append(
        _event(
            child,
            offset,
            EventType.MODEL_RESPONSE_DELTA,
            {"model_call_id": "late", "content_delta": "prefix"},
        )
    )
    scope = queue.read_pending_projection_work()[0].scope
    consumer = AgUiCheckpointConsumer(tasks, queue, namespace="local")
    _page_spy(tasks, monkeypatch)
    clock = [10_000.0]
    monkeypatch.setattr("agent_storage.projection_work.time.time", lambda: clock[0])
    read_page = tasks.read_event_page

    def transient(*args, **kwargs):
        raise RuntimeError("temporary source I/O")

    if prior_failures:
        monkeypatch.setattr(tasks, "read_event_page", transient)
        for _ in range(30):
            consumer.poll_once(budget_seconds=2)
            clock[0] += 3601
            problem = queue.read_projection_work_problem(scope)
            if problem is not None and problem.attempts == prior_failures:
                break
        assert problem.code == "projection_failed" and problem.attempts == prior_failures
        assert problem.retry_at is not None
        monkeypatch.setattr(tasks, "read_event_page", read_page)
    for _ in range(8):
        consumer.poll_once(budget_seconds=2)
        clock[0] += 3601
    problem = queue.read_projection_work_problem(scope)
    assert problem is not None and problem.code == "not_ready" and problem.retry_at is None
    assert problem.attempts == prior_failures
    assert tasks.read_checkpoint_head(scope).through_sequence == -1

    handoff = str(uuid4())
    _append(
        events,
        task,
        1,
        EventType.SESSION_HANDOFF_COMMITTED,
        {"handoff_id": handoff, "target_session_id": str(child)},
    )
    events.append(
        _event(
            child,
            1 + offset,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": handoff, "parent_session_id": str(task.active_segment_id)},
        )
    )
    assert queue.read_projection_work_problem(scope) is None, (
        "admission wait retained a prior transient failure cap after canonical source wake"
    )
    assert failure_count(queue, scope) == prior_failures, "source wake reset real failure history"
    for _ in range(8):
        consumer.poll_once(budget_seconds=2)
    assert tasks.read_checkpoint_head(scope).through_sequence == 3 + 2 * offset
    assert failure_count(queue, scope) == prior_failures


def test_native_two_consumers_ack_same_target_only_at_current_closure_revision(
    native_source, monkeypatch
):
    tasks, events, queue = native_source
    task = _task(tasks)
    _command(events, task)
    stale = queue.read_pending_projection_work()[0]
    first = AgUiCheckpointConsumer(tasks, queue, namespace="local")
    second = _consumer(_restore(tasks), queue)
    entered, release = Event(), Event()
    acknowledgements = []
    complete = queue.complete_projection_work

    def ack(work, *, expected_through):
        if work == stale:
            entered.set()
            assert release.wait(timeout=4), "stale ACK barrier was not released"
        accepted = complete(work, expected_through=expected_through)
        acknowledgements.append((work.revision, accepted))
        return accepted

    monkeypatch.setattr(queue, "complete_projection_work", ack)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(first.materialize_once, stale)
        try:
            assert entered.wait(timeout=2)
            _command(events, task, 1, run="next")
            closed = next(
                row for row in queue.read_pending_projection_work() if row.run_id == "run"
            )
            assert (
                closed.requested_through
                == closed.closed_through
                == stale.requested_through
                == _source_offset(tasks)
            )
            assert closed.revision > stale.revision
            assert second.materialize_once(closed)
            assert {row.run_id for row in queue.read_pending_projection_work()} == {"next"}
        finally:
            release.set()
        assert pending.result(timeout=4)
    assert acknowledgements == [(closed.revision, True), (stale.revision, False)]
    assert tasks.read_checkpoint_head(stale.scope).through_sequence == _source_offset(tasks)
    assert queue.read_projection_work_problem(stale.scope) is None


@pytest.mark.parametrize("interval", [0, 0.009, 2.1, float("nan")])
def test_invalid_poll_interval_creates_no_background_thread(interval):
    with pytest.raises(ValueError):
        AgUiProjectionWorkService(Ticks(), interval_seconds=interval)

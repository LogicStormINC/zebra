"""Native consumer probes on disposable SQLite/PG stores, never test-built checkpoints."""

from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.sessions import Session
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionScope,
)
from agent_core.ports.task_projection_work import ProjectionWorkRepair
from agent_integrations.ag_ui.binding_resolution import BindingResolutionPending
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.checkpoint_plan import AG_UI_CHECKPOINT_VERSION
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    sqlite_control_plane_stores,
)
from agent_storage.projection_work import SQLiteTaskProjectionWorkStore
from agent_storage.projection_work_schema import initialize_projection_work

from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import (
    _append,
    _attach,
    _command,
    _consumer,
    _deny_source_bodies,
    _forbid_history,
    _native,
    _page_spy,
    _prefix_sources,
    _restore,
    _source_offset,
    _task,
    assert_cold_cursor_oracle,
    assert_transport_problem,
    observe_unchanged,
    persist_problem,
    prepare_source_projections,
)
from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import (
    native_source as _native_source_fixture,
)
from tests.agent_integrations.test_ag_ui_projection import _event, _golden_events
from tests.agent_storage.test_projection_work_native import native_dsn as native_dsn

native_source = _native_source_fixture


def test_native_discovery_and_empty_checkpoint_reads_are_body_free_and_write_free(
    tmp_path, monkeypatch
):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    reads, writes = [], []
    source_connect, queue_connect = tasks._database.connect, queue._connect

    def trace(sql):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            writes.append(sql)

    @contextmanager
    def source():
        connection = source_connect()
        _deny_source_bodies(connection, reads)
        connection.set_trace_callback(trace)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def queue_read(*, write=False):
        assert not write, "metadata discovery attempted queue mutation"
        with queue_connect() as connection:
            _deny_source_bodies(connection, reads)
            connection.set_trace_callback(trace)
            yield connection

    monkeypatch.setattr(tasks._database, "connect", source)
    monkeypatch.setattr(queue, "_connect", queue_read)
    _forbid_history(tasks, monkeypatch)
    pending = queue.read_pending_projection_work()
    assert len(pending) == 1 and pending[0].after_sequence == -1
    assert not queue.read_projection_work_repairs()
    run = tasks.read_run_header(task.task_id, "run")
    assert tasks.read_event_header(task.task_id, 0) == run.anchor
    assert tasks.read_checkpoint_head(pending[0].scope).through_sequence == -1
    assert reads == writes == []


def test_native_oversized_next_event_is_rejected_before_body_hydration(tmp_path, monkeypatch):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    _append(events, task, 1, payload={"scratch": "x" * 1_048_576})
    consumer = _consumer(tasks, queue)
    work = queue.read_pending_projection_work()[0]
    assert consumer.materialize_once(work)  # Only the small anchor fits this Page.
    assert tasks.read_checkpoint_head(work.scope).through_sequence == 0
    reads = []
    original = tasks._database.connect

    @contextmanager
    def guarded():
        connection = original()
        _deny_source_bodies(connection, reads)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    monkeypatch.setattr(tasks._database, "connect", guarded)
    _forbid_history(tasks, monkeypatch)
    consumer.poll_once(budget_seconds=2)
    assert reads == [], "oversized source was hydrated before byte admission"
    problem = queue.read_projection_work_problem(work.scope)
    assert problem is not None and problem.attempts == 1
    assert tasks.read_checkpoint_head(work.scope).through_sequence == 0


def test_native_pending_round_robin_builds_small_task_before_large_task_second_page(tmp_path):
    tasks, events, queue = _native(tmp_path)
    large, small = _task(tasks, ordinal=1), _task(tasks, ordinal=2)
    _command(events, large)
    for position in range(1, 300):
        _append(events, large, position)
    _command(events, small)
    works = {row.scope.task_id: row for row in queue.read_pending_projection_work()}
    consumer = _consumer(tasks, queue)
    consumer.poll_once(limit=1, budget_seconds=2)
    assert tasks.read_checkpoint_head(works[large.task_id].scope).through_sequence == 255
    assert tasks.read_checkpoint_head(works[small.task_id].scope).through_sequence == -1
    consumer.poll_once(limit=1, budget_seconds=2)
    assert tasks.read_checkpoint_head(works[large.task_id].scope).through_sequence == 255
    assert tasks.read_checkpoint_head(works[small.task_id].scope).through_sequence == 0


@pytest.mark.parametrize("count,padding", [(600, 0), (8, 180_000)])
def test_native_consumer_advances_one_bounded_page_per_work_without_history(
    tmp_path, monkeypatch, count, padding
):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    for position in range(1, count):
        _append(events, task, position, payload={"scratch": "x" * padding})
    work = queue.read_pending_projection_work()[0]
    assert tasks.read_checkpoint_head(work.scope).through_sequence == -1
    _forbid_history(tasks, monkeypatch)
    pages = _page_spy(tasks, monkeypatch)
    consumer = _consumer(tasks, queue)
    for _ in range(count):
        pending = queue.read_pending_projection_work()
        if not pending:
            break
        before = len(pages)
        assert consumer.materialize_once(pending[0])
        assert len(pages) == before + 1
        assert tasks.read_checkpoint_head(work.scope).through_sequence == pages[-1].next_sequence
    assert not queue.read_pending_projection_work()
    assert len(pages) > 1
    assert sum(len(page.events) for page in pages) == count
    assert tasks.read_checkpoint_head(work.scope).through_sequence == count - 1


def test_native_pre_anchor_warming_and_cold_restore_match_task_projector(
    native_source, monkeypatch
):
    tasks, events, queue = native_source
    task = _task(tasks)
    offset = _source_offset(tasks)
    sources = _prefix_sources(tasks, task)
    if offset:
        sources.append(_append(events, task, 0, EventType.TASK_PREPARED,
                               {"title": "Pre-anchor", "user_input": "Inspect"}))
    sources += [
        _append(events, task, offset,
            EventType.MODEL_RESPONSE_DELTA, {"model_call_id": "old", "content_delta": "prefix"},
        ),
        _command(events, task, 1 + offset),
        _append(events, task, 2 + offset,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "old", "assistant_message": "prefix"},
        ),
    ]
    prepare_source_projections(tasks, sources)
    work = queue.read_pending_projection_work()[0]
    _forbid_history(tasks, monkeypatch)
    assert _consumer(tasks, queue).materialize_once(work)
    restored = _restore(tasks)
    _forbid_history(restored, monkeypatch)
    identity = AgUiRunIdentity(
        session_id=task.active_segment_id, thread_id=str(task.task_id), run_id="run")
    observer = AgUiCheckpointObserver(restored, namespace="local")
    snapshot = observer.snapshot(task.task_id, identity)
    page = observer.read_page(snapshot, snapshot.run.start - 1)
    assert page is not None
    actual = list(observer.iter_page_frames(snapshot, page, identity))
    expected = list(AgUiTaskProjector().project_task_events(sources, identity))
    assert actual == expected


def test_production_sqlite_composition_routes_native_append_to_consumer(tmp_path):
    stores = sqlite_control_plane_stores(tmp_path / "production-wiring.sqlite")
    queue = stores.projection_work
    assert queue is not None, "production composition has no checkpoint work queue"
    queue.enable_projection_work()
    task = _task(stores.tasks)
    _command(stores.events, task)
    pending = queue.read_pending_projection_work()
    assert len(pending) == 1, "native append did not enqueue production derived work"
    assert _consumer(stores.tasks, queue).materialize_once(pending[0])
    assert stores.tasks.read_checkpoint_head(pending[0].scope).through_sequence == 0
    assert not queue.read_pending_projection_work()


@pytest.mark.parametrize("field,value", [("namespace", "other"), ("projector_version", "other")])
def test_wrong_namespace_or_version_rejected_before_source_or_checkpoint_reads(
    tmp_path, monkeypatch, field, value
):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    work = queue.read_pending_projection_work()[0]
    pages = _page_spy(tasks, monkeypatch)
    consumer = _consumer(tasks, queue)
    with pytest.raises(CheckpointConflict):
        consumer.materialize_once(replace(work, scope=replace(work.scope, **{field: value})))
    assert pages == [] and queue.read_pending_projection_work() == (work,)
    assert tasks.read_checkpoint_head(work.scope).through_sequence == -1


def test_append_between_commit_and_ack_keeps_new_revision_pending(tmp_path, monkeypatch):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    stale = queue.read_pending_projection_work()[0]
    complete = queue.complete_projection_work
    results = []

    def raced_ack(work, *, expected_through):
        if not results:
            _append(events, task, 1)
        result = complete(work, expected_through=expected_through)
        results.append(result)
        return result

    monkeypatch.setattr(queue, "complete_projection_work", raced_ack)
    consumer = _consumer(tasks, queue)
    assert consumer.materialize_once(stale)
    pending = queue.read_pending_projection_work()[0]
    assert results == [False]
    assert pending.revision > stale.revision and pending.requested_through == 1
    assert pending.after_sequence == 0
    assert consumer.materialize_once(pending)
    assert results == [False, True] and not queue.read_pending_projection_work()


def test_stale_work_with_newer_committed_head_is_benign_not_invalid_ack(tmp_path):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    stale = queue.read_pending_projection_work()[0]
    _append(events, task, 1)
    newer = queue.read_pending_projection_work()[0]
    assert _consumer(tasks, queue).materialize_once(newer)
    assert not _consumer(tasks, queue).materialize_once(stale)
    assert not queue.read_pending_projection_work()


def test_native_competing_consumer_cas_is_benign_and_never_double_commits(tmp_path, monkeypatch):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    work = queue.read_pending_projection_work()[0]
    other = _consumer(SQLiteAgentTaskStore(tasks._database.database_path), queue)
    original = tasks.commit_projection_page
    races = []

    def commit(transition):
        races.append(other.materialize_once(work))
        return original(transition)

    monkeypatch.setattr(tasks, "commit_projection_page", commit)
    assert not _consumer(tasks, queue).materialize_once(work)
    assert races == [True]
    assert tasks.read_checkpoint_head(work.scope).through_sequence == 0
    assert not queue.read_pending_projection_work()


def test_competitor_between_head_and_prepare_does_not_persist_false_integrity(
    tmp_path, monkeypatch
):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    for position in range(1, 300):
        _append(events, task, position)
    work = queue.read_pending_projection_work()[0]
    other = _consumer(SQLiteAgentTaskStore(tasks._database.database_path), queue)
    read = tasks.read_event_page
    raced = []

    def source(*args, **kwargs):
        if not raced:
            raced.append(other.materialize_once(work))
        return read(*args, **kwargs)

    monkeypatch.setattr(tasks, "read_event_page", source)
    consumer = _consumer(tasks, queue)
    consumer.poll_once(budget_seconds=2)
    assert raced == [True]
    assert tasks.read_checkpoint_head(work.scope).through_sequence >= 255
    assert queue.read_projection_work_problem(work.scope) is None, (
        "normal head CAS race became integrity"
    )
    for _ in range(4):
        consumer.poll_once(budget_seconds=2)
    assert tasks.read_checkpoint_head(work.scope).through_sequence == 299
    assert not queue.read_pending_projection_work()


def test_run_window_closes_at_next_executable_without_projecting_its_body(tmp_path):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    first = _command(events, task)
    _append(events, task, 1)
    _command(events, task, 2, run="next")
    work = next(row for row in queue.read_pending_projection_work() if row.run_id == "run")
    assert work.scope.anchor_event_id == first.event.event_id
    assert work.closed_through == work.requested_through == 1
    assert _consumer(tasks, queue).materialize_once(work)
    assert tasks.read_checkpoint_head(work.scope).through_sequence == 1
    with pytest.raises(CheckpointNotReady):
        tasks.read_event_projection_header(work.scope, 2)


@pytest.mark.parametrize(
    "failure,code",
    [
        (CheckpointConflict("private integrity detail"), "integrity"),
        (RuntimeError("private provider token"), "projection_failed"),
    ],
)
def test_fault_is_persisted_redacted_and_other_task_still_materializes(
    tmp_path, monkeypatch, failure, code
):
    tasks, events, queue = _native(tmp_path)
    bad, good = _task(tasks, ordinal=1), _task(tasks, ordinal=2)
    _command(events, bad)
    _command(events, good)
    work = {row.scope.task_id: row for row in queue.read_pending_projection_work()}
    original = tasks.read_event_page

    def fail_one(task_id, *args, **kwargs):
        if task_id == bad.task_id:
            raise failure
        return original(task_id, *args, **kwargs)

    monkeypatch.setattr(tasks, "read_event_page", fail_one)
    _consumer(tasks, queue).poll_once(budget_seconds=2)
    problem = SQLiteTaskProjectionWorkStore(
        tasks._database.database_path, "local", AG_UI_CHECKPOINT_VERSION
    ).read_projection_work_problem(work[bad.task_id].scope)
    assert problem is not None, "consumer logged a fault but did not persist observation problem"
    assert problem.code == code and problem.attempts == 1
    assert "private" not in repr(problem)
    if code == "integrity":
        assert problem.retry_at is None
    assert tasks.read_checkpoint_head(work[good.task_id].scope).through_sequence == 0


def test_temporary_fault_retries_are_finite_and_problem_survives_consumer_recreation(
    tmp_path, monkeypatch
):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    scope = queue.read_pending_projection_work()[0].scope
    clock, attempts = [10_000.0], []
    monkeypatch.setattr("agent_storage.projection_work.time.time", lambda: clock[0])

    def failed_read(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("temporary source failure")

    monkeypatch.setattr(tasks, "read_event_page", failed_read)
    for _ in range(40):
        _consumer(tasks, queue).poll_once(budget_seconds=2)
        clock[0] += 3601
    problem = queue.read_projection_work_problem(scope)
    assert problem is not None and problem.attempts <= 8
    assert 1 < len(attempts) <= 8, "temporary errors were never retried or retried without bound"
    assert problem.retry_at is None, "finite retry budget did not leave a persistent problem"
    before = len(attempts)
    for _ in range(5):
        _consumer(tasks, queue).poll_once(budget_seconds=2)
        clock[0] += 3601
    assert len(attempts) == before
    _append(events, task, 1)
    assert queue.read_projection_work_problem(scope) == problem
    _consumer(tasks, queue).poll_once(budget_seconds=2)
    assert len(attempts) == before, "new source revived an exhausted transient failure"


def test_native_binding_budget_not_ready_is_not_infinite_successful_source_repair(
    tmp_path, monkeypatch
):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    child = _attach(tasks, task.task_id, task.active_segment_id)
    # Valid canonical orphan receives, but >256 lookahead headers is deliberately
    # outside binding's bounded admission. Source maintenance cannot fix that.
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
    assert tasks.backfill_event_positions(task.task_id)
    assert tasks.backfill_replay_headers(task.task_id)
    batches = []
    for _ in range(3):
        batches.append(tasks.backfill_projection_sources(task.task_id))
        if batches[-1]:
            break
    # Completion resets the frozen repair cursor. Another call starts a new
    # 258-row cycle; its False would not contradict the previous True.
    assert batches == [False, True]
    assert (
        tasks.read_projection_block(task.task_id, 1, through_sequence=257).last_task_sequence == 257
    )
    consumer = _consumer(tasks, queue)
    run = tasks.read_run_header(task.task_id, work.run_id, through_sequence=work.requested_through)
    page = tasks.read_event_page(task.task_id, -1, through_sequence=run.highwater)
    identity = AgUiRunIdentity(
        session_id=task.active_segment_id, thread_id=str(task.task_id), run_id=work.run_id
    )
    with pytest.raises(BindingResolutionPending, match="budget") as pending:
        build_projection_page_plan(tasks, page, run, work.scope, identity)
    assert pending.value.reason == "budget"
    assert pending.value.resolved_through == -1 and pending.value.required_through == 257
    assert consumer.materialize_once(work) is False
    clock = [10_000.0]
    monkeypatch.setattr("agent_storage.projection_work.time.time", lambda: clock[0])
    for _ in range(20):
        consumer.poll_once(budget_seconds=2)
        clock[0] += 3601
    problem = queue.read_projection_work_problem(work.scope)
    assert problem is not None, "unrepairable bounded binding kept retrying without durable problem"
    assert 0 <= problem.attempts <= 8 and problem.retry_at is None
    assert problem.code == "not_ready" and problem.attempts == 0
    assert tasks.read_checkpoint_head(work.scope).through_sequence == -1
    cold_queue = SQLiteTaskProjectionWorkStore(
        tasks._database.database_path, "local", AG_UI_CHECKPOINT_VERSION
    )
    assert cold_queue.read_projection_work_problem(work.scope) == problem

    def hot_work(*args, **kwargs):
        raise AssertionError("unchanged admission wait performed hot repair/materialization")

    for name in (
        "backfill_event_positions",
        "backfill_replay_headers",
        "backfill_projection_sources",
        "read_event_page",
    ):
        monkeypatch.setattr(tasks, name, hot_work)
    monkeypatch.setattr(queue, "defer_projection_work", hot_work)
    for _ in range(5):
        consumer.poll_once(budget_seconds=2)
        clock[0] += 3601
    assert cold_queue.read_projection_work_problem(work.scope) == problem


def test_failed_explicit_repair_does_not_abort_other_pending_tasks(tmp_path, monkeypatch):
    tasks, events, queue = _native(tmp_path)
    bad, good = _task(tasks, ordinal=1), _task(tasks, ordinal=2)
    _command(events, bad)
    _command(events, good)
    work = {row.scope.task_id: row for row in queue.read_pending_projection_work()}
    read = tasks.read_event_page

    def unavailable(task, *args, **kwargs):
        if task == bad.task_id:
            raise CheckpointNotReady("source requires repair")
        return read(task, *args, **kwargs)

    def failed_repair(*args, **kwargs):
        raise RuntimeError("repair I/O unavailable")

    monkeypatch.setattr(tasks, "read_event_page", unavailable)
    monkeypatch.setattr(tasks, "backfill_projection_sources", failed_repair)
    _consumer(tasks, queue).poll_once(budget_seconds=2)
    assert tasks.read_checkpoint_head(work[good.task_id].scope).through_sequence == 0
    assert queue.read_projection_work_problem(work[bad.task_id].scope) is not None


def test_blocked_smallest_repair_task_cannot_starve_next_task(tmp_path, monkeypatch):
    tasks, events, queue = _native(tmp_path)
    bad, good = _task(tasks, ordinal=1), _task(tasks, ordinal=2)
    queue.disable_projection_work()
    for task in (bad, good):
        _command(events, task)
    queue.enable_projection_work()
    for task in (bad, good):
        _append(events, task, 1)
    original = tasks.backfill_event_positions

    def blocked(task, *, limit=256):
        assert limit <= 256
        return False if task == bad.task_id else original(task, limit=limit)

    monkeypatch.setattr(tasks, "backfill_event_positions", blocked)
    consumer = _consumer(tasks, queue)
    for _ in range(4):
        consumer.repair_once()
    pending = queue.read_pending_projection_work()
    assert any(row.scope.task_id == good.task_id for row in pending), (
        "repair always picked bad Task"
    )


def test_real_legacy_backfill_false_is_progress_across_more_than_three_pages(tmp_path):
    path = tmp_path / "legacy-consumer.sqlite"
    session = Session.create(title="Legacy source")
    events = SQLiteEventStore(path)
    SQLiteProjectionStore(path).save_session(session)
    for position in range(800):
        kind = (
            EventType.SESSION_COMMAND_ACCEPTED
            if position == 0
            else EventType.MEMORY_EXTRACTION_COMPLETED
        )
        payload = {"kind": "run", "payload": {"run_id": "legacy-native"}} if position == 0 else {}
        events.append(_event(session.session_id, position, kind, payload))
    tasks = SQLiteAgentTaskStore(path)
    task = tasks.ensure_for_session(session.session_id)
    with tasks._database.connect() as connection:
        initialize_projection_work(connection)
    queue = SQLiteTaskProjectionWorkStore(path, "local", AG_UI_CHECKPOINT_VERSION)
    queue.enable_projection_work()

    class LegacyDiscovery:
        """Discovery-only fake until queue's migration discovery is composed."""

        def __getattr__(self, name: str) -> Any:
            return getattr(queue, name)

        def read_projection_work_repairs(self, *, limit=32, after_task_id=None):
            assert limit <= 32
            if after_task_id is not None:
                return ()
            return (
                ProjectionWorkRepair(
                    ProjectionScope("local", task.task_id, None, AG_UI_CHECKPOINT_VERSION),
                    -1,
                    799,
                    True,
                ),
            )

    consumer = _consumer(tasks, LegacyDiscovery())
    for _ in range(32):
        consumer.repair_once()
        if queue.read_pending_projection_work():
            break
    pending = queue.read_pending_projection_work()
    assert pending and pending[0].requested_through >= 0
    for _ in range(32):
        consumer.repair_once()
    pending = queue.read_pending_projection_work()
    assert pending[0].requested_through == 799, "bounded repair progress was mistaken for failure"

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("full history")

    tasks.read_events = _forbidden
    for _ in range(10):
        consumer.poll_once(budget_seconds=2)
        if not queue.read_pending_projection_work():
            break
    assert tasks.read_checkpoint_head(pending[0].scope).through_sequence == 799


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": True},
        {"limit": 33},
        {"budget_seconds": 0},
        {"budget_seconds": float("nan")},
    ],
)
def test_invalid_tick_budget_is_rejected_before_queue_io(tmp_path, monkeypatch, kwargs):
    tasks, _, queue = _native(tmp_path)

    def forbidden(**_):
        raise AssertionError("invalid consumer budget reached queue")

    monkeypatch.setattr(queue, "read_pending_projection_work", forbidden)
    with pytest.raises(ValueError):
        _consumer(tasks, queue).poll_once(**kwargs)


def test_native_full_text_tool_terminal_output_and_each_cursor_survive_cold_restore(
    native_source, monkeypatch
):
    tasks, events, queue = native_source
    task = _task(tasks)
    sources = _prefix_sources(tasks, task) + [_command(events, task)]
    for event in _golden_events(task.active_segment_id):
        sources.append(_append(events, task, event.sequence + 1, event.event_type, event.payload))
    prepare_source_projections(tasks, sources)
    _forbid_history(tasks, monkeypatch)
    pages = _page_spy(tasks, monkeypatch)
    consumer = _consumer(tasks, queue)
    for _ in range(8):
        consumer.poll_once(budget_seconds=2)
        if not queue.read_pending_projection_work():
            break
    assert not queue.read_pending_projection_work()
    scope = ProjectionScope(
        "local",
        task.task_id,
        sources[_source_offset(tasks)].event.event_id,
        AG_UI_CHECKPOINT_VERSION,
    )
    head = tasks.read_checkpoint_head(scope)
    assert head.through_sequence == head.terminal.task_sequence == 7 + _source_offset(tasks)
    assert queue.read_projection_work_problem(scope) is None and pages
    identity = AgUiRunIdentity(
        session_id=task.active_segment_id, thread_id=str(task.task_id), run_id="run"
    )
    assert_cold_cursor_oracle(tasks, task, identity, sources, monkeypatch)


@pytest.mark.parametrize("fault", ["budget", "retryable", "exhausted", "not_ready"])
def test_native_observation_problem_is_typed_without_task_failure(
    native_source, monkeypatch, fault
):
    tasks, events, queue = native_source
    task = _task(tasks)
    sources = _prefix_sources(tasks, task) + [_command(events, task)]
    prepare_source_projections(tasks, sources)
    work, problem = persist_problem(queue, fault, monkeypatch)
    assert problem is not None
    assert problem.attempts == (8 if fault == "exhausted" else 0 if fault == "not_ready" else 1)
    assert (problem.retry_at is not None) == (fault == "retryable")
    frame = observe_unchanged(tasks, queue, task, monkeypatch)
    if fault == "not_ready":
        assert frame == ": keepalive\n\n"
    else:
        code = {
            "budget": "projection_budget_exceeded",
            "retryable": "projection_retry_scheduled",
            "exhausted": "observation_unavailable",
        }[fault]
        assert_transport_problem(frame, code, retryable=fault == "retryable")
    assert queue.read_projection_work_problem(work.scope) == problem


@pytest.mark.parametrize("field", ["namespace", "task_id", "anchor_event_id", "projector_version"])
def test_native_foreign_problem_scope_is_transport_conflict_not_task_failure(
    native_source, monkeypatch, field
):
    tasks, events, queue = native_source
    task = _task(tasks)
    sources = _prefix_sources(tasks, task) + [_command(events, task)]
    prepare_source_projections(tasks, sources)
    work = queue.read_pending_projection_work()[0]
    assert queue.defer_projection_work(work, problem_code="integrity")
    problem = queue.read_projection_work_problem(work.scope)
    foreign = "foreign" if field in {"namespace", "projector_version"} else uuid4()
    corrupt = replace(problem, scope=replace(work.scope, **{field: foreign}))
    original = queue.read_projection_work_problem
    monkeypatch.setattr(queue, "read_projection_work_problem", lambda scope: corrupt)
    frame = observe_unchanged(tasks, queue, task, monkeypatch)
    assert_transport_problem(frame, "projection_conflict", retryable=False)
    assert original(work.scope) == problem

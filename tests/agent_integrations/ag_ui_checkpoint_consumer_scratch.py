"""Disposable native source wiring shared by consumer and Worker quality tests."""

import asyncio
import json
import sqlite3
from pathlib import Path
from threading import Event
from time import monotonic
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.ports.agent_tasks import TaskEvent
from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.checkpoint_plan import AG_UI_CHECKPOINT_VERSION
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage import (
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresProjectionStore,
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    bootstrap_control_plane_epoch,
    postgres_control_plane_stores,
)
from agent_storage.postgres.task_replay_coverage_privacy_migration import (
    TASK_REPLAY_COVERAGE_PRIVACY_MIGRATION,
)
from agent_storage.projection_work import SQLiteTaskProjectionWorkStore
from agent_storage.projection_work_schema import initialize_projection_work
from zebra_agent_api.ag_ui_checkpoint_tail import tail_checkpoint_frames
from zebra_agent_worker.ag_ui_projection_work import AgUiProjectionWorkService

from tests.agent_integrations.test_ag_ui_projection import _event
from tests.agent_storage.test_checkpoint_quality_probes import _attach as sqlite_attach
from tests.agent_storage.test_postgres_agent_tasks import _worker_authority
from tests.agent_storage.test_postgres_control_plane_composition import _ObjectReader


def _native(tmp_path: Path, *, dsn=None):
    if dsn is not None:
        # The standalone queue fixture stays frozen at v68. Composing current
        # replay readers additionally requires the real source-owned privacy
        # view, not a test-built replacement or a removed privacy predicate.
        with psycopg.connect(dsn) as connection:
            assert connection.execute("SELECT current_schema()").fetchone()[0].startswith(
                "projection_work_native_"
            )
            for statement in TASK_REPLAY_COVERAGE_PRIVACY_MIGRATION.statements:
                connection.execute(statement)
        bootstrap_control_plane_epoch(dsn, deployment_namespace="local")
        scope = OpaqueAuthorityScope(authority_issuer="test", namespace_id="test")
        stores = postgres_control_plane_stores(
            dsn,
            deployment_namespace="local",
            memory_cursor_signing_key=b"k" * 32,
            artifact_objects=_ObjectReader(),
            history_scope=scope,
            continuation_scope=scope,
        )
        assert stores.projection_work is not None
        stores.projection_work.enable_projection_work()
        return stores.tasks, stores.events, stores.projection_work
    path = tmp_path / "consumer.sqlite"
    tasks = SQLiteAgentTaskStore(path)
    with tasks._database.connect() as connection:
        initialize_projection_work(connection)
    queue = SQLiteTaskProjectionWorkStore(path, "local", AG_UI_CHECKPOINT_VERSION)
    queue.enable_projection_work()
    return tasks, SQLiteEventStore(path), queue


@pytest.fixture(params=["sqlite", "postgres"])
def native_source(request, tmp_path):
    dsn = request.getfixturevalue("native_dsn") if request.param == "postgres" else None
    return _native(tmp_path, dsn=dsn)


def _projections(tasks):
    if isinstance(tasks, PostgresAgentTaskStore):
        return PostgresProjectionStore(tasks._database._dsn, deployment_namespace="local")
    return SQLiteProjectionStore(tasks._database.database_path)


def _restore(tasks):
    if isinstance(tasks, PostgresAgentTaskStore):
        return PostgresAgentTaskStore(tasks._database._dsn, deployment_namespace="local")
    return SQLiteAgentTaskStore(tasks._database.database_path)


def _task(tasks, *, ordinal=1):
    session = Session.create(title="Consumer source").model_copy(
        update={"session_id": SessionId(UUID(int=ordinal))}
    )
    _save_initial_session(tasks, session)
    return tasks.ensure_for_session(session.session_id)


def _attach(tasks, task_id, root):
    if not isinstance(tasks, PostgresAgentTaskStore):
        return sqlite_attach(tasks, task_id, root)
    child = Session.create(title="Scratch child")
    _save_initial_session(tasks, child)
    authority = _worker_authority(tasks._database._dsn, "local", root)
    tasks.attach_segment_for_worker(
        task_id,
        child.session_id,
        predecessor_id=root,
        reason=RolloverReason.CONTEXT_PRESSURE,
        authority=authority,
    )
    return child.session_id


def _save_initial_session(tasks, session):
    if isinstance(tasks, PostgresAgentTaskStore):
        created = _event(session.session_id, 0, EventType.SESSION_CREATED, {"title": session.title})
        PostgresEventStore(tasks._database._dsn, deployment_namespace="local").append(created)
        session = rebuild_session([created])
    _projections(tasks).save_session(session)


def _source_offset(tasks):
    return int(isinstance(tasks, PostgresAgentTaskStore))


def _prefix_sources(tasks, task, *, after=-1):
    if not _source_offset(tasks):
        return []
    page = tasks.read_event_page(task.task_id, after, limit=1)
    assert len(page.events) == 1 and page.events[0].event.event_type == EventType.SESSION_CREATED
    return list(page.events)


def _append(events, task, sequence, kind=EventType.MEMORY_EXTRACTION_COMPLETED, payload=None):
    sequence += int(isinstance(events, PostgresEventStore))
    event = _event(task.active_segment_id, sequence, kind, payload or {})
    events.append(event)
    return TaskEvent(task.task_id, sequence, task.active_segment_id, sequence, event)


def _command(events, task, sequence=0, run="run"):
    return _append(
        events,
        task,
        sequence,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"kind": "run", "payload": {"run_id": run}},
    )


def orphan_sources(tasks, events, task):
    sources = _prefix_sources(tasks, task) + [_command(events, task)]
    if _source_offset(tasks):
        # Bootstrap warms RunStarted before the anchor; retain a real frame in
        # the closed window so its cold cursor test is not vacuous.
        sources.append(
            _append(
                events,
                task,
                1,
                EventType.TASK_PREPARED,
                {"title": "Inspect repository", "user_input": "Inspect"},
            )
        )
    return sources


def _consumer(tasks, queue):
    return AgUiCheckpointConsumer(tasks, queue, namespace="local")


def _forbid_history(tasks, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("consumer attempted full-history/implicit-adoption API")

    for name in (
        "get_task",
        "list_tasks",
        "segments",
        "read_events",
        "rebuild_all",
        "ensure_for_session",
    ):
        monkeypatch.setattr(tasks, name, forbidden)


def _page_spy(tasks, monkeypatch):
    pages = []
    original = tasks.read_event_page

    def read(task, after, *, limit=256, max_bytes=1_048_576, through_sequence=None):
        assert 1 <= limit <= 256 and 0 < max_bytes <= 1_048_576
        page = original(
            task, after, limit=limit, max_bytes=max_bytes, through_sequence=through_sequence
        )
        assert len(page.events) <= limit and page.byte_count <= max_bytes
        assert page.highwater == through_sequence
        pages.append(page)
        return page

    monkeypatch.setattr(tasks, "read_event_page", read)
    return pages


def _deny_source_bodies(connection, reads):
    def authorize(action, table, column, *_):
        if action == sqlite3.SQLITE_READ and table == "session_events" and column == "payload":
            reads.append((table, column))
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorize)


def assert_cold_cursor_oracle(tasks, task, identity, sources, monkeypatch):
    expected = list(AgUiTaskProjector().project_task_events(sources, identity))
    assert expected, "fixture must exercise public output"
    for index in range(-1, len(expected)):
        restored = _restore(tasks)
        _forbid_history(restored, monkeypatch)
        _page_spy(restored, monkeypatch)
        observer = AgUiCheckpointObserver(restored, namespace="local")
        snapshot = observer.snapshot(task.task_id, identity)
        cursor = None if index < 0 else expected[index][0]
        observer.validate_cursor(snapshot, identity, cursor)
        after = snapshot.run.start - 1 if cursor is None else cursor.sequence - 1
        actual = []
        while (page := observer.read_page(snapshot, after)) is not None:
            actual.extend(observer.iter_page_frames(snapshot, page, identity, after=cursor))
            after = page.next_sequence
        assert actual == expected[index + 1 :], f"cold resume skipped/duplicated frame {index}"


def first_observation(tasks, queue, task, identity):
    context = SimpleNamespace(
        stores=SimpleNamespace(tasks=tasks, projection_work=queue),
        task_id=task.task_id,
        identity=identity,
        deployment_namespace="local",
        cursor=None,
        command_outcome=None,
        host_context=None,
    )

    class Request:
        stopped = False

        async def is_disconnected(self):
            return self.stopped

    async def read():
        request = Request()
        stream = tail_checkpoint_frames(
            context,
            request,
            monotonic() + 2,
            poll_seconds=0.01,
            keepalive_seconds=0,
        )
        try:
            frame = await anext(stream)
            request.stopped = True
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
            return frame
        finally:
            await stream.aclose()

    return asyncio.run(read())


def observe_unchanged(tasks, queue, task, monkeypatch):
    before = (
        _restore(tasks).get_task(task.task_id),
        _projections(tasks).get_session(task.active_segment_id),
    )
    run = tasks.read_run_header(task.task_id, "run")
    _forbid_history(tasks, monkeypatch)
    identity = AgUiRunIdentity(
        session_id=task.active_segment_id, thread_id=str(task.task_id), run_id="run"
    )
    frame = first_observation(tasks, queue, task, identity)
    assert (
        _restore(tasks).get_task(task.task_id),
        _projections(tasks).get_session(task.active_segment_id),
    ) == before
    assert tasks.read_run_header(task.task_id, "run") == run
    return frame


def persist_problem(queue, fault, monkeypatch):
    work = queue.read_pending_projection_work()[0]
    clock = [10_000.0]
    monkeypatch.setattr("agent_storage.projection_work.time.time", lambda: clock[0])
    code = fault if fault in {"budget", "not_ready"} else "projection_failed"
    for attempt in range(8 if fault == "exhausted" else 1):
        assert queue.defer_projection_work(
            work,
            problem_code=code,
            retry_after_seconds=1 if code == "projection_failed" else None,
        )
        if fault == "exhausted" and attempt < 7:
            clock[0] += 2
            assert queue.retry_due_projection_work() == 1
            work = queue.read_pending_projection_work()[0]
    return work, queue.read_projection_work_problem(work.scope)


def assert_transport_problem(frame, code, *, retryable):
    payload = json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))
    assert payload == {
        "type": "CUSTOM",
        "name": "zebra.observation.problem",
        "value": {"code": code, "retryable": retryable},
    }


class Ticks:
    def __init__(self):
        self.work = self
        self.enables = 0
        self.calls = 0
        self.tick = Event()
        self.enable_error = None
        self.poll_error = None
        self.enabled = Event()

    def enable_projection_work(self):
        self.enables += 1
        self.enabled.set()
        if self.enable_error is not None:
            raise self.enable_error

    def bootstrap_projection_work(self, *, limit=32):
        assert 1 <= limit <= 32
        return True  # Lifecycle fake only; native discovery has its own production test.

    def poll_once(self):
        self.calls += 1
        if self.poll_error is not None and self.calls == 1:
            raise self.poll_error
        self.tick.set()
        return 0


def _service(consumer):
    return AgUiProjectionWorkService(consumer, interval_seconds=0.01)


def _no_thread(service):
    assert service._thread is None or not service._thread.is_alive()

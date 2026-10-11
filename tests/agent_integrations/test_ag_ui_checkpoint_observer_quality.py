"""Independent bounded-observer probes; databases are pytest scratch only."""

from dataclasses import replace
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.domain.sessions import Session
from agent_core.ports.agent_tasks import TaskEventPage
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionFrameHeader,
    ProjectionScope,
    ProjectionTransition,
    SegmentCheckpoint,
)
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.checkpoint_plan import (
    AG_UI_CHECKPOINT_VERSION,
    ProjectionEventPlan,
    ProjectionPagePlan,
)
from agent_integrations.ag_ui.contracts import AgUiCursor, AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore
from agent_storage.postgres.task_projection_checkpoints_migration import (
    TASK_PROJECTION_CHECKPOINTS_MIGRATION,
)
from agent_storage.postgres.task_replay_headers import read_event_header as pg_event_header
from agent_storage.postgres.task_replay_headers import read_run_header as pg_run_header
from psycopg import sql
from psycopg.rows import dict_row

from tests.agent_integrations.test_ag_ui_projection import _event
from tests.agent_storage.test_checkpoint_quality_probes import _attach, _observer_fixture, _wire
from tests.agent_storage.test_postgres_scalar_task_replay_headers import (
    NS as PG_NS,
)
from tests.agent_storage.test_postgres_scalar_task_replay_headers import (
    install as pg_install,
)
from tests.agent_storage.test_postgres_scalar_task_replay_headers import (
    scratch as _pg_header_scratch,
)
from tests.agent_storage.test_postgres_scalar_task_replay_headers import (
    seed as pg_seed,
)
from tests.agent_storage.test_postgres_task_projection_checkpoints import _store as pg_store
from tests.agent_storage.test_scalar_task_replay_headers import source_row

header_scratch = _pg_header_scratch


def _prefix_fixture(tmp_path, *, incomplete=False, closed=True):
    database = tmp_path / "observer.sqlite"
    root = Session.create(title="Observer scratch")
    SQLiteProjectionStore(database).save_session(root)
    tasks = SQLiteAgentTaskStore(database)
    task = tasks.ensure_for_session(root.session_id)
    child = _attach(tasks, task.task_id, root.session_id)
    sources = (
        _event(
            root.session_id,
            0,
            EventType.MODEL_RESPONSE_DELTA,
            {"model_call_id": "old", "content_delta": "prefix"},
        ),
        _event(
            root.session_id,
            1,
            EventType.TOOL_CALL_PROPOSED,
            {"tool_call_id": "tool", "tool_name": "read", "arguments": {}},
        ),
        _event(
            root.session_id,
            2,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "run", "payload": {"run_id": "bound"}},
        ),
        _event(
            root.session_id,
            3,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "old", "assistant_message": "prefix"},
        ),
        _event(
            child,
            0,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "orphan", "assistant_message": "not admitted"},
        ),
        _event(
            root.session_id,
            4,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "run", "payload": {"run_id": "next"}},
        ),
        _event(
            root.session_id, 5, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "next run"}
        ),
    )
    if not closed:
        sources = sources[:5]
    for source in sources:
        SQLiteEventStore(database).append(source)
    page = tasks.read_event_page(task.task_id, -1)
    identity = AgUiRunIdentity(
        session_id=root.session_id, thread_id=str(task.task_id), run_id="bound"
    )
    run = tasks.read_run_header(task.task_id, identity.run_id)
    scope = ProjectionScope("local", task.task_id, run.anchor.event_id, AG_UI_CHECKPOINT_VERSION)
    selected = page.events[:3] if incomplete else page.events
    prepared_page = TaskEventPage(selected, -1, run.highwater, page.byte_count)
    plan = ProjectionPagePlan(
        run,
        tuple(
            ProjectionEventPlan(
                tasks.read_event_header(task.task_id, entry.task_sequence),
                entry.task_sequence < 4,
                2 <= entry.task_sequence < 4,
            )
            for entry in selected
        ),
    )
    transition = AgUiCheckpointMaterializer(tasks).prepare_page(
        prepared_page, plan, scope, identity
    )
    assert transition is not None
    tasks.commit_projection_page(transition)
    observer = AgUiCheckpointObserver(tasks, namespace="local")
    return observer, observer.snapshot(task.task_id, identity), identity, page.events


def _cursor(entry, identity, *, frame_index=None):
    return AgUiCursor(
        thread_id=identity.thread_id,
        run_id=identity.run_id,
        sequence=entry.task_sequence,
        event_id=str(entry.event.event_id),
        frame_index=frame_index,
    )


def test_observer_whole_start_minus_one_preserves_existing_replay_parity(tmp_path):
    observer, snapshot, identity, entries = _prefix_fixture(tmp_path)
    cursor = _cursor(entries[snapshot.run.start - 1], identity)
    AgUiTaskProjector().validate_task_cursor(entries, identity, after=cursor)
    observer.validate_cursor(snapshot, identity, cursor)
    page = observer.read_page(snapshot, cursor.sequence)
    assert page is not None and page.next_sequence == snapshot.run.stop - 1
    actual = list(map(_wire, observer.iter_page_frames(snapshot, page, identity, after=cursor)))
    expected = list(
        map(_wire, AgUiTaskProjector().project_task_events(entries, identity, after=cursor))
    )
    assert actual == expected


@pytest.mark.parametrize("position,frame", [(0, None), (1, 0), (5, None), (5, 0)])
def test_observer_rejects_earlier_prefix_partial_sentinel_and_run_stop(tmp_path, position, frame):
    observer, snapshot, identity, entries = _prefix_fixture(tmp_path)
    with pytest.raises(AgUiProjectionError):
        observer.validate_cursor(
            snapshot, identity, _cursor(entries[position], identity, frame_index=frame)
        )


def test_observer_missing_partial_checkpoint_is_typed_not_ready_not_invalid(tmp_path):
    observer, snapshot, identity, entries = _prefix_fixture(tmp_path, incomplete=True)
    with pytest.raises(CheckpointNotReady):
        observer.validate_cursor(snapshot, identity, _cursor(entries[3], identity, frame_index=0))
    # Whole-Event tokens need canonical metadata, not a speculative frame count.
    observer.validate_cursor(snapshot, identity, _cursor(entries[3], identity))


def test_observer_unready_source_is_typed_not_ready(tmp_path):
    observer, snapshot, identity, _ = _prefix_fixture(tmp_path)
    with observer.tasks._database.connect() as connection:
        connection.execute(
            "UPDATE agent_tasks SET event_position_state='assigning' WHERE task_id=?",
            (str(snapshot.run.task_id),),
        )
    with pytest.raises(CheckpointNotReady):
        observer.snapshot(snapshot.run.task_id, identity)


@pytest.mark.parametrize("fault", ["event_id", "segment_id", "segment_sequence", "task_id"])
def test_observer_ineligible_rows_still_require_exact_canonical_frame_identity(tmp_path, fault):
    observer, snapshot, identity, entries = _prefix_fixture(tmp_path)
    entry = entries[4]
    header = observer.tasks.read_event_projection_header(snapshot.head.scope, entry.task_sequence)
    assert header is not None and not header.eligible
    if fault == "event_id":
        entry = replace(entry, event=entry.event.model_copy(update={"event_id": EventId(uuid4())}))
    elif fault == "segment_id":
        segment = SessionId(uuid4())
        entry = replace(
            entry, segment_id=segment, event=entry.event.model_copy(update={"session_id": segment})
        )
    elif fault == "segment_sequence":
        entry = replace(
            entry, segment_sequence=99, event=entry.event.model_copy(update={"sequence": 99})
        )
    else:
        entry = replace(entry, task_id=TaskId(uuid4()))
    # A malformed page must not become an accepted silent source watermark.
    page = TaskEventPage((entry,), 3, snapshot.through, 100)
    with pytest.raises(CheckpointConflict):
        list(observer.iter_page_frames(snapshot, page, identity))


def test_observer_snapshot_accepts_legitimate_append_between_run_and_head_reads(tmp_path):
    materializer, scope, _, identity, _ = _observer_fixture(tmp_path / "append.sqlite")
    tasks = materializer.port
    observer = AgUiCheckpointObserver(tasks, namespace="local")
    original = tasks.read_checkpoint_head
    appended = False
    published = None

    def read_head(requested_scope):
        nonlocal appended, published
        if not appended:
            appended = True
            tail = _event(
                identity.session_id, 7, EventType.SESSION_TITLE_UPDATED, {"title": "tail"}
            )
            SQLiteEventStore(tasks._database.database_path).append(tail)
            run = tasks.read_run_header(scope.task_id, identity.run_id)
            page = tasks.read_event_page(scope.task_id, 6, limit=1)
            plan = ProjectionPagePlan(
                run,
                (
                    ProjectionEventPlan(
                        tasks.read_event_header(scope.task_id, 7),
                        True,
                        True,
                    ),
                ),
            )
            transition = materializer.prepare_page(page, plan, scope, identity)
            assert transition is not None
            published = tasks.commit_projection_page(transition)
        return original(requested_scope)

    tasks.read_checkpoint_head = read_head
    snapshot = observer.snapshot(scope.task_id, identity)
    assert appended and published is not None and published.through_sequence == 7
    assert snapshot.head.through_sequence <= snapshot.run.highwater


def _publish_tail(materializer, scope, identity):
    tasks = materializer.port
    SQLiteEventStore(tasks._database.database_path).append(
        _event(identity.session_id, 7, EventType.SESSION_TITLE_UPDATED, {"title": "tail"})
    )
    run = tasks.read_run_header(scope.task_id, identity.run_id)
    page = tasks.read_event_page(scope.task_id, 6, limit=1)
    plan = ProjectionPagePlan(
        run, (ProjectionEventPlan(tasks.read_event_header(scope.task_id, 7), True, True),)
    )
    transition = materializer.prepare_page(page, plan, scope, identity)
    assert transition is not None
    tasks.commit_projection_page(transition)
    return run


@pytest.mark.parametrize("fault", ["task_id", "run_id"])
def test_observer_refresh_rejects_changed_legacy_run_identity(tmp_path, monkeypatch, fault):
    materializer, scope, _, identity, captured = _observer_fixture(tmp_path / "identity.sqlite")
    tasks = materializer.port
    refreshed = _publish_tail(materializer, scope, identity)
    changed = replace(
        refreshed, **({"task_id": TaskId(uuid4())} if fault == "task_id" else {"run_id": "foreign"})
    )
    reads = 0

    def read_run(task_id, run_id):
        nonlocal reads
        assert task_id == scope.task_id and run_id == identity.run_id
        reads += 1
        assert reads <= 2, "refresh must not become a polling loop"
        return captured if reads == 1 else changed

    monkeypatch.setattr(tasks, "read_run_header", read_run)
    observer = AgUiCheckpointObserver(tasks, namespace="local")
    # The source append and derived head are genuine. Only the refreshed Port
    # record is faulty: a legacy anchor cannot implicitly protect Task/Run IDs.
    with pytest.raises((CheckpointConflict, CheckpointNotReady)):
        observer.snapshot(scope.task_id, identity)
    assert reads == 2


def test_observer_rejects_genuinely_future_head_after_one_refresh(tmp_path, monkeypatch):
    materializer, scope, _, identity, captured = _observer_fixture(tmp_path / "future.sqlite")
    tasks = materializer.port
    head = tasks.read_checkpoint_head(scope)
    future = replace(head, through_sequence=7, last_event_id=EventId(uuid4()))
    reads = {"run": 0, "head": 0}

    def read_run(task_id, run_id):
        assert task_id == scope.task_id and run_id == identity.run_id
        reads["run"] += 1
        assert reads["run"] <= 2, "future head must not cause unbounded retries"
        return captured

    def read_head(requested_scope):
        assert requested_scope == scope
        reads["head"] += 1
        return future

    monkeypatch.setattr(tasks, "read_run_header", read_run)
    monkeypatch.setattr(tasks, "read_checkpoint_head", read_head)
    with pytest.raises(CheckpointConflict):
        AgUiCheckpointObserver(tasks, namespace="local").snapshot(scope.task_id, identity)
    assert reads == {"run": 2, "head": 1}


@pytest.mark.parametrize("changed", [{"legacy": False}, {"control_only": True}])
def test_observer_refresh_rejects_changed_binding_modes(tmp_path, monkeypatch, changed):
    materializer, scope, _, identity, captured = _observer_fixture(tmp_path / "mode.sqlite")
    tasks = materializer.port
    refreshed = replace(_publish_tail(materializer, scope, identity), **changed)
    reads = 0

    def read_run(task_id, run_id):
        nonlocal reads
        assert task_id == scope.task_id and run_id == identity.run_id
        reads += 1
        assert reads <= 2
        return captured if reads == 1 else refreshed

    monkeypatch.setattr(tasks, "read_run_header", read_run)
    with pytest.raises(CheckpointNotReady):
        AgUiCheckpointObserver(tasks, namespace="local").snapshot(scope.task_id, identity)
    assert reads == 2


@pytest.mark.parametrize("fault", ["task_id", "run_id"])
def test_observer_rejects_initial_run_from_another_real_sqlite_locator(
    tmp_path, monkeypatch, fault
):
    materializer, scope, _, identity, _ = _observer_fixture(tmp_path / "initial.sqlite")
    tasks = materializer.port
    if fault == "task_id":
        foreign = Session.create(title="Foreign scratch Task")
        SQLiteProjectionStore(tasks._database.database_path).save_session(foreign)
        foreign_task = tasks.ensure_for_session(foreign.session_id)
        for sequence in range(7):
            SQLiteEventStore(tasks._database.database_path).append(
                _event(
                    foreign.session_id, sequence, EventType.SESSION_TITLE_UPDATED, {"title": "x"}
                )
            )
        wrong = tasks.read_run_header(foreign_task.task_id, identity.run_id)
    else:
        wrong = tasks.read_run_header(scope.task_id, "foreign")
    assert wrong.highwater == 6
    # Fault routing only: the returned record itself comes from the real adapter,
    # not a fabricated mock header. An initial read has no refresh comparison.
    monkeypatch.setattr(tasks, "read_run_header", lambda task_id, run_id: wrong)
    with pytest.raises((CheckpointConflict, AgUiProjectionError)):
        AgUiCheckpointObserver(tasks, namespace="local").snapshot(scope.task_id, identity)


@pytest.mark.parametrize("publish_head", [False, True], ids=["source-only", "derived-head-too"])
def test_observer_command_append_freezes_window_without_rejecting_new_stop(
    tmp_path, monkeypatch, publish_head
):
    observer, captured, identity, _ = _prefix_fixture(tmp_path, closed=False)
    tasks, scope = observer.tasks, captured.head.scope
    assert captured.run.highwater == 4 and captured.run.stop is None
    read_run, read_head = tasks.read_run_header, tasks.read_checkpoint_head
    calls, appended = [], False

    def counted_run(task_id, run_id):
        result = read_run(task_id, run_id)
        calls.append(result)
        return result

    def append_before_head(requested_scope):
        nonlocal appended
        if not appended:
            appended = True
            SQLiteEventStore(tasks._database.database_path).append(
                _event(
                    identity.session_id,
                    4,
                    EventType.SESSION_COMMAND_ACCEPTED,
                    {"kind": "run", "payload": {"run_id": "next"}},
                )
            )
            if publish_head:
                run = read_run(scope.task_id, identity.run_id)
                page = tasks.read_event_page(scope.task_id, 4)
                plan = ProjectionPagePlan(
                    run,
                    (ProjectionEventPlan(tasks.read_event_header(scope.task_id, 5), False, False),),
                )
                transition = observer.materializer.prepare_page(page, plan, scope, identity)
                assert transition is not None
                tasks.commit_projection_page(transition)
        return read_head(requested_scope)

    monkeypatch.setattr(tasks, "read_run_header", counted_run)
    monkeypatch.setattr(tasks, "read_checkpoint_head", append_before_head)
    frozen = observer.snapshot(scope.task_id, identity)
    assert appended and len(calls) == (2 if publish_head else 1)
    assert frozen.run.highwater == (5 if publish_head else 4)
    assert frozen.run.stop == (5 if publish_head else None)
    assert frozen.through == captured.through == 4
    page = observer.read_page(frozen, frozen.run.start - 1)
    assert page is not None and page.highwater == page.next_sequence == 4
    frames = list(observer.iter_page_frames(frozen, page, identity))
    assert all(cursor.sequence < 5 for cursor, _ in frames)
    latest = read_run(scope.task_id, identity.run_id)
    assert latest.stop == 5 and latest.highwater == 5
    assert captured.run.stop is None and captured.run.highwater == 4


@pytest.mark.parametrize(
    "position,fault",
    [
        (3, "readiness"),
        (3, "source_cursor"),
        (4, "readiness"),
        (4, "source_cursor"),
        (4, "membership"),
    ],
)
def test_observer_whole_cursor_obeys_same_source_guards_as_frame_header(tmp_path, position, fault):
    observer, snapshot, identity, entries = _prefix_fixture(tmp_path)
    tasks, entry = observer.tasks, entries[position]
    if fault == "membership":
        foreign = Session.create(title="Foreign membership scratch")
        SQLiteProjectionStore(tasks._database.database_path).save_session(foreign)
        foreign_task = tasks.ensure_for_session(foreign.session_id)
        field, value = "task_id", str(foreign_task.task_id)
    elif fault == "readiness":
        field, value = "event_position_source_ready", 0
    else:
        field, value = "event_position_source_cursor", entry.segment_sequence - 1
    # Fault only the scratch DB's metadata, leaving exact immutable Event IDs,
    # Task/source sequences and bodies intact. Both readers see the same state.
    with tasks._database.connect() as connection:
        connection.execute(
            f"UPDATE execution_segments SET {field}=? WHERE session_id=?",
            (value, str(entry.segment_id)),
        )
    with pytest.raises((CheckpointConflict, CheckpointNotReady)):
        tasks.read_event_projection_header(snapshot.head.scope, position)
    with pytest.raises((CheckpointConflict, CheckpointNotReady)):
        observer.validate_cursor(snapshot, identity, _cursor(entry, identity))


def test_observer_preflight_and_first_frame_are_read_only_and_never_hydrate_history(
    tmp_path, monkeypatch
):
    observer, captured, identity, entries = _prefix_fixture(tmp_path)
    tasks, statements = observer.tasks, []
    connect = tasks._database.connect

    def traced_connect():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    def forbidden(*args, **kwargs):
        raise AssertionError("observation must not hydrate history or project during preflight")

    monkeypatch.setattr(tasks._database, "connect", traced_connect)
    for method in ("get_task", "segments", "read_events"):
        monkeypatch.setattr(tasks, method, forbidden)
    with monkeypatch.context() as preflight:
        preflight.setattr(observer.materializer.projector, "project_events", forbidden)
        snapshot = observer.snapshot(captured.run.task_id, identity)
        observer.validate_cursor(snapshot, identity, _cursor(entries[1], identity))
        observer.validate_cursor(snapshot, identity, _cursor(entries[3], identity, frame_index=0))
        assert not any("SELECT * FROM SESSION_EVENTS" in sql.upper() for sql in statements)
    page = observer.read_page(snapshot, snapshot.run.start - 1)
    assert page is not None and len(page.events) <= 256 and page.byte_count <= 1_048_576
    project = observer.materializer.projector.project_events
    projected = []

    def counted(events, run_identity, *, state=None):
        projected.extend(events)
        return project(events, run_identity, state=state)

    monkeypatch.setattr(observer.materializer.projector, "project_events", counted)
    stream = observer.iter_page_frames(snapshot, page, identity)
    try:
        cursor, _ = next(stream)
        # This real fixture's command anchor is silent after prefix warming.
        # Only that anchor and the first emitting Event may be projected;
        # yielding a frame must not eagerly traverse the remaining Page tail.
        assert cursor.sequence == entries[3].task_sequence
        assert tuple(event.event_id for event in projected) == tuple(
            entry.event.event_id for entry in page.events[:2]
        )
    finally:
        stream.close()
    body_reads = [sql for sql in statements if "SELECT * FROM SESSION_EVENTS" in sql.upper()]
    assert len(body_reads) == 1 and "LIMIT 3" in body_reads[0].upper()
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
        for sql in statements
    )


@pytest.mark.parametrize("position", [2, 5], ids=["anchor", "stop"])
def test_sqlite_run_header_checks_anchor_and_stop_source_cursor(tmp_path, position):
    observer, snapshot, identity, entries = _prefix_fixture(tmp_path)
    entry = entries[position]
    with observer.tasks._database.connect() as connection:
        connection.execute(
            "UPDATE execution_segments SET event_position_source_cursor=? WHERE session_id=?",
            (entry.segment_sequence - 1, str(entry.segment_id)),
        )
    with pytest.raises(CheckpointConflict):
        observer.tasks.read_run_header(snapshot.run.task_id, identity.run_id)


@pytest.mark.parametrize(
    "fault",
    ["none", "readiness", "source_cursor", "membership", "namespace", "position", "anchor", "stop"],
)
def test_real_pg_metadata_matches_frame_source_guard_without_payload_privilege(
    header_scratch, fault
):
    dsn, role = header_scratch
    task, child = TaskId(uuid4()), SessionId(uuid4())
    rows = [
        source_row(task, 0),
        source_row(task, 1, body='{"title":"silent"}'),
        source_row(task, 2, run="next"),
    ]
    rows[1] = (*rows[1][:1], str(child), 0, "session_title_updated", *rows[1][4:])
    rows[2] = (*rows[2][:2], 1, *rows[2][3:])
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        pg_install(connection)
        pg_seed(connection, task, rows, 3)
        # No derived table exists yet: whole-Event observation must not require one.
        assert pg_event_header(connection, PG_NS, task, 1).segment_id == child
        assert pg_run_header(connection, PG_NS, task, "latest", 1).stop is None
        assert pg_run_header(connection, PG_NS, task, "latest", None).stop == 2
        for statement in TASK_PROJECTION_CHECKPOINTS_MIGRATION.statements:
            connection.execute(statement)
    scope = ProjectionScope(PG_NS, task, None, AG_UI_CHECKPOINT_VERSION)
    store = pg_store(dsn, PG_NS)
    store.commit_projection_page(
        ProjectionTransition(
            scope,
            -1,
            (
                ProjectionFrameHeader(
                    0,
                    EventId(UUID(rows[0][0])),
                    SessionId(task),
                    0,
                    -1,
                    1,
                    True,
                    True,
                ),
                ProjectionFrameHeader(1, EventId(UUID(rows[1][0])), child, 0, -1, 0, False, False),
                ProjectionFrameHeader(
                    2,
                    EventId(UUID(rows[2][0])),
                    SessionId(task),
                    1,
                    -1,
                    0,
                    False,
                    False,
                ),
            ),
            (SegmentCheckpoint(SessionId(task), 0, 0, True, False),),
            (),
        )
    )
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        if fault in {"readiness", "source_cursor", "membership", "namespace"}:
            field, value = {
                "readiness": ("event_position_source_ready", False),
                "source_cursor": ("event_position_source_cursor", -1),
                "membership": ("task_id", uuid4()),
                "namespace": ("deployment_namespace", "foreign"),
            }[fault]
            connection.execute(
                sql.SQL("UPDATE execution_segments SET {}=%s WHERE session_id=%s").format(
                    sql.Identifier(field)
                ),
                (value, child),
            )
        elif fault == "position":
            connection.execute("UPDATE agent_tasks SET next_event_sequence=1")
        elif fault in {"anchor", "stop"}:
            connection.execute(
                "UPDATE execution_segments SET event_position_source_cursor=%s WHERE session_id=%s",
                (-1 if fault == "anchor" else 0, task),
            )
        connection.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
        schema = connection.execute("SELECT current_schema() AS s").fetchone()["s"]
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        connection.execute(
            sql.SQL("""GRANT SELECT (deployment_namespace,task_id,task_sequence,
          event_id,session_id,sequence,event_type,replay_command_kind,replay_run_id,
          replay_internal_continuation,replay_header_ready)
          ON session_events TO {}""").format(
                sql.Identifier(role)
            )
        )
        connection.execute(
            sql.SQL("GRANT SELECT ON task_replay_coverage_privacy TO {}").format(
                sql.Identifier(role)
            )
        )
        connection.execute(
            sql.SQL("GRANT SELECT ON agent_tasks,execution_segments TO {}").format(
                sql.Identifier(role)
            )
        )
    statements = []
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))

        class Reader:
            def execute(self, query, parameters=()):
                statements.append(query)
                return connection.execute(query, parameters)

        reader = Reader()
        assert pg_event_header(reader, "foreign", task, 1) is None
        if fault == "none":
            assert pg_event_header(reader, PG_NS, task, 1).segment_id == child
            assert pg_run_header(reader, PG_NS, task, "latest", None).stop == 2
        else:
            with pytest.raises(CheckpointConflict):
                if fault in {"anchor", "stop"}:
                    pg_run_header(reader, PG_NS, task, "latest", None)
                else:
                    pg_event_header(reader, PG_NS, task, 1)
    assert statements and all(query.lstrip().upper().startswith("SELECT") for query in statements)
    assert all("payload" not in query.lower() for query in statements)
    assert all("task_projection_" not in query.lower() for query in statements)
    if fault == "none":
        assert store.read_event_projection_header(scope, 1).frame_count == 0
    else:
        with pytest.raises(CheckpointConflict):
            store.read_event_projection_header(scope, 1)

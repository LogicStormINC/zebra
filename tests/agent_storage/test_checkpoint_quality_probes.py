"""Independent scratch-only canonical admission and cold-process replay probes."""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import groupby
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import Session
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCellKey,
    ProjectionScope,
)
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import (
    AG_UI_CHECKPOINT_VERSION,
    ProjectionEventPlan,
    ProjectionHandoffProof,
    ProjectionPagePlan,
)
from agent_integrations.ag_ui.contracts import AgUiCursor, AgUiRunIdentity
from agent_integrations.ag_ui.task_run_binding import bind_task_run
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore
from agent_storage.agent_tasks import TASK_SCHEMA, attach_segment_locked
from agent_storage.database import SQLiteDatabase
from agent_storage.task_event_positions import initialize_task_positions
from agent_storage.task_replay_header_schema import initialize_task_replay_headers

from tests.agent_integrations.test_ag_ui_projection import _event, _golden_events
from tests.agent_storage.test_task_projection_checkpoints import _fixture, _transition


def _scratch_schema(database: Path) -> None:
    # Native explicit schema setup isolates checkpoints from concurrent facade
    # integration. This is scratch-only, not a workaround in production callers.
    SQLiteEventStore(database)
    with SQLiteDatabase(database).connect() as connection:
        connection.executescript(TASK_SCHEMA)
        initialize_task_positions(connection)
        initialize_task_replay_headers(connection)


def _attach(store: SQLiteAgentTaskStore, task_id: TaskId, root: SessionId) -> SessionId:
    child = Session.create(title="Scratch child")
    SQLiteProjectionStore(store._database.database_path).save_session(child)
    with store._database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        attach_segment_locked(
            connection,
            task_id=task_id,
            segment_id=child.session_id,
            predecessor_id=root,
            reason=RolloverReason.CONTEXT_PRESSURE,
        )
    return child.session_id


@pytest.mark.parametrize("anchored", [False, True], ids=["legacy", "anchored"])
@pytest.mark.parametrize("fault", ["readiness", "cursor", "highwater"])
def test_sqlite_commit_rejects_page_outside_canonical_coverage(tmp_path, anchored, fault):
    _scratch_schema(tmp_path / "coverage.sqlite")
    store, scope, events = _fixture(tmp_path / "coverage.sqlite")
    child = _attach(store, scope.task_id, events[0].session_id)
    tail = _event(child, 0, EventType.SESSION_TITLE_UPDATED, {"title": "child"})
    SQLiteEventStore(store._database.database_path).append(tail)
    if anchored:
        scope = replace(scope, anchor_event_id=events[0].event_id)
    transition = _transition(scope, (*events, tail))
    transition = replace(
        transition,
        headers=(
            *transition.headers[:-1],
            replace(transition.headers[-1], state_before_sequence=-1),
        ),
    )
    # Fault only scratch metadata, after the observer has prepared its page.
    # The root/anchor remains valid, so anchor-only validation cannot cover this.
    with store._database.connect() as connection:
        if fault == "readiness":
            connection.execute(
                "UPDATE execution_segments SET event_position_source_ready=0 WHERE session_id=?",
                (str(child),),
            )
        elif fault == "cursor":
            connection.execute(
                "UPDATE execution_segments SET event_position_source_cursor=-1 WHERE session_id=?",
                (str(child),),
            )
        else:
            connection.execute(
                "UPDATE agent_tasks SET next_event_sequence=3 WHERE task_id=?",
                (str(scope.task_id),),
            )
    with pytest.raises((CheckpointConflict, CheckpointNotReady)):
        store.commit_projection_page(transition)
    with store._database.connect() as connection:
        for table in ("heads", "frames", "scalars", "cells"):
            assert (
                connection.execute(f"SELECT count(*) FROM task_projection_{table}").fetchone()[0]
                == 0
            )


@pytest.mark.parametrize("anchored", [False, True], ids=["legacy", "anchored"])
def test_sqlite_head_rejects_frontier_above_canonical_highwater(tmp_path, anchored):
    _scratch_schema(tmp_path / "head.sqlite")
    store, scope, events = _fixture(tmp_path / "head.sqlite")
    if anchored:
        scope = replace(scope, anchor_event_id=events[0].event_id)
    store.commit_projection_page(_transition(scope, events))
    with store._database.connect() as connection:
        connection.execute(
            "UPDATE agent_tasks SET next_event_sequence=2 WHERE task_id=?", (str(scope.task_id),)
        )
    with pytest.raises(CheckpointConflict):
        store.read_checkpoint_head(scope)


def _wire(pair):
    cursor, frame = pair
    return [
        cursor.model_dump(mode="json"),
        frame.model_dump(mode="json", by_alias=True, exclude_none=True),
    ]


def _cold_restore(database: Path, task_text: str, root_text: str) -> dict:
    """Called only in a fresh interpreter; no parent state or source history."""
    store = SQLiteAgentTaskStore(database)
    task_id, root = TaskId(UUID(task_text)), SessionId(UUID(root_text))
    identity = AgUiRunIdentity(session_id=root, thread_id=task_text, run_id="probe-run")
    statements = []
    connect = store._database.connect

    def traced():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    def forbid_history(*_, **__):
        raise AssertionError("cold restore attempted full Task hydration")

    store._database.connect = traced
    store.read_events = forbid_history
    run = store.read_run_header(task_id, identity.run_id)
    scope = ProjectionScope("local", task_id, run.anchor.event_id, AG_UI_CHECKPOINT_VERSION)
    materializer = AgUiCheckpointMaterializer(store)
    actual, suffixes = [], []
    for position in range(run.start, run.stop or run.highwater + 1):
        header = store.read_event_projection_header(scope, position)
        if not header.eligible:
            continue
        page = store.read_event_page(task_id, position - 1, limit=1, through_sequence=run.highwater)
        assert len(page.events) == 1 and page.byte_count <= 1_048_576
        entry = page.events[0]
        frames = list(materializer.iter_event_frames(scope, entry, identity, run=run))
        actual.extend(map(_wire, frames))
        for cursor, _ in frames:
            tail = materializer.iter_event_frames(scope, entry, identity, run=run, after=cursor)
            suffixes.append([cursor.model_dump(mode="json"), list(map(_wire, tail))])
            whole = cursor.model_copy(update={"frame_index": None})
            assert (
                list(materializer.iter_event_frames(scope, entry, identity, run=run, after=whole))
                == []
            )
    bodies = [sql for sql in statements if "SELECT * FROM session_events" in sql]
    assert bodies and all("LIMIT 1" in sql for sql in bodies)
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
    )
    return {"pid": os.getpid(), "frames": actual, "suffixes": suffixes, "body_reads": len(bodies)}


@pytest.mark.parametrize("chunk", [1, 2, 256])
def test_sqlite_checkpoint_restore_in_fresh_process_preserves_exact_frames(tmp_path, chunk):
    database = tmp_path / "cold.sqlite"
    _scratch_schema(database)
    root = Session.create(title="Scratch run")
    SQLiteProjectionStore(database).save_session(root)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root.session_id)
    child = _attach(store, task.task_id, root.session_id)
    handoff = uuid4()
    sources = (
        _event(
            root.session_id,
            0,
            EventType.MODEL_RESPONSE_DELTA,
            {"model_call_id": "old", "content_delta": "hello"},
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
            {"kind": "run", "payload": {"run_id": "probe-run"}},
        ),
        _event(
            root.session_id,
            3,
            EventType.TOOL_EXECUTION_COMPLETED,
            {"tool_call_id": "tool", "output": "done"},
        ),
        _event(
            root.session_id,
            4,
            EventType.APPROVAL_REQUESTED,
            {"tool_call_id": "approve", "reason": "scratch reason"},
        ),
        _event(root.session_id, 5, EventType.APPROVAL_GRANTED, {"tool_call_id": "approve"}),
        _event(
            root.session_id,
            6,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(child)},
        ),
        _event(
            child,
            0,
            EventType.MODEL_RESPONSE_DELTA,
            {"model_call_id": "child", "content_delta": "child text"},
        ),
        _event(
            child,
            1,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(handoff), "parent_session_id": str(root.session_id)},
        ),
        _event(
            child,
            2,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "child", "assistant_message": "child text"},
        ),
        _event(
            root.session_id,
            7,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "old", "assistant_message": "hello"},
        ),
        _event(root.session_id, 8, EventType.TURN_COMPLETED, {}),
        _event(root.session_id, 9, EventType.MODEL_REQUEST_STARTED, {}),
        _event(root.session_id, 10, EventType.SESSION_COMPLETED, {}),
        _event(
            root.session_id,
            11,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "run", "payload": {"run_id": "next-run"}},
        ),
        _event(
            root.session_id,
            12,
            EventType.MODEL_RESPONSE_DELTA,
            {"model_call_id": "outside", "content_delta": "not this run"},
        ),
    )
    for source in sources:
        SQLiteEventStore(database).append(source)
    events = store.read_event_page(task.task_id, -1).events
    assert tuple(e.event.event_id for e in events) == tuple(e.event_id for e in sources)
    identity = AgUiRunIdentity(
        session_id=root.session_id, thread_id=str(task.task_id), run_id="probe-run"
    )
    run = store.read_run_header(task.task_id, identity.run_id)
    scope = ProjectionScope("local", task.task_id, run.anchor.event_id, AG_UI_CHECKPOINT_VERSION)
    binding = bind_task_run(events, identity.run_id)  # Full-history oracle only in parent.
    warm = set()
    for _, rows in groupby(events, key=lambda e: e.segment_id):
        block = tuple(rows)
        selected = [e for e in block if binding.includes(e)]
        if selected:
            warm.update(
                e.task_sequence for e in block if e.task_sequence <= selected[-1].task_sequence
            )
    decisions = tuple(
        ProjectionEventPlan(
            store.read_event_header(task.task_id, e.task_sequence),
            e.task_sequence in warm,
            binding.includes(e),
        )
        for e in events
    )
    proof = ProjectionHandoffProof(handoff, decisions[6].source, decisions[8].source)
    materializer = AgUiCheckpointMaterializer(store)
    after = -1
    while after < run.highwater:
        page = store.read_event_page(
            task.task_id, after, limit=chunk, through_sequence=run.highwater
        )
        plan = ProjectionPagePlan(run, decisions[after + 1 : page.next_sequence + 1], (proof,))
        transition = materializer.prepare_page(page, plan, scope, identity)
        assert transition is not None
        store.commit_projection_page(transition)
        after = page.next_sequence
    expected = list(map(_wire, AgUiTaskProjector().project_task_events(events, identity)))
    command = (
        "import json,sys; from pathlib import Path; "
        "from tests.agent_storage.test_checkpoint_quality_probes import _cold_restore; "
        "print(json.dumps(_cold_restore(Path(sys.argv[1]), sys.argv[2], sys.argv[3])))"
    )
    child_result = subprocess.run(
        [sys.executable, "-c", command, str(database), str(task.task_id), str(root.session_id)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    restored = json.loads(child_result.stdout)
    assert restored["pid"] != os.getpid()
    assert restored["frames"] == expected
    for cursor, suffix in restored["suffixes"]:
        assert suffix == [
            pair
            for pair in expected
            if pair[0]["sequence"] == cursor["sequence"]
            and pair[0]["frame_index"] > cursor["frame_index"]
        ]
    head = store.read_checkpoint_head(scope)
    assert head.through_sequence == run.highwater
    assert head.terminal.task_sequence == 11
    assert store.read_event_projection_header(scope, 10).state_before_sequence == 6
    assert store.read_event_projection_header(scope, 13).frame_count == 0


@pytest.mark.parametrize("observation", ["head", "frame"])
@pytest.mark.parametrize("field", ["event_id", "segment_id", "segment_sequence"])
def test_point_frame_observation_rejects_noncanonical_coordinates(tmp_path, observation, field):
    database = tmp_path / "frame.sqlite"
    _scratch_schema(database)
    store, scope, events = _fixture(database)
    store.commit_projection_page(_transition(scope, events))
    # The canonical source and head identity stay intact; only the derived
    # locator changes. Reconstructing a recovery cursor must reject this row.
    replacement = 99 if field == "segment_sequence" else str(uuid4())
    with store._database.connect() as connection:
        connection.execute(
            f"UPDATE task_projection_frames SET {field}=? WHERE task_sequence=2",
            (replacement,),
        )
    with pytest.raises(CheckpointConflict):
        if observation == "head":
            store.read_checkpoint_head(scope)
        else:
            store.read_event_projection_header(scope, 2)


def test_point_scalar_observation_rejects_noncanonical_source_sequence(tmp_path):
    database = tmp_path / "scalar.sqlite"
    _scratch_schema(database)
    store, scope, events = _fixture(database)
    store.commit_projection_page(_transition(scope, events))
    with store._database.connect() as connection:
        connection.execute(
            "UPDATE task_projection_scalars SET segment_sequence=0 WHERE task_sequence=1"
        )
    with pytest.raises(CheckpointConflict):
        store.read_segment_checkpoint_before(scope, events[0].session_id, 2)


def _observer_fixture(database: Path, *, bound: bool = False):
    _scratch_schema(database)
    root = Session.create(title="Scratch observer")
    SQLiteProjectionStore(database).save_session(root)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root.session_id)
    sources = _golden_events(root.session_id)
    if bound:
        sources = (
            sources[0].model_copy(
                update={
                    "event_type": EventType.SESSION_COMMAND_ACCEPTED,
                    "payload": {"kind": "run", "payload": {"run_id": "legacy"}},
                }
            ),
            *sources[1:],
            _event(
                root.session_id,
                7,
                EventType.SESSION_COMMAND_ACCEPTED,
                {"kind": "run", "payload": {"run_id": "next"}},
            ),
        )
    for event in sources:
        SQLiteEventStore(database).append(event)
    page = store.read_event_page(task.task_id, -1)
    identity = AgUiRunIdentity(
        session_id=root.session_id, thread_id=str(task.task_id), run_id="legacy"
    )
    run = store.read_run_header(task.task_id, identity.run_id)
    scope = ProjectionScope(
        "local", task.task_id, run.anchor.event_id if run.anchor else None, AG_UI_CHECKPOINT_VERSION
    )
    plan = ProjectionPagePlan(
        run,
        tuple(
            ProjectionEventPlan(
                store.read_event_header(task.task_id, entry.task_sequence),
                run.stop is None or entry.task_sequence < run.stop,
                run.stop is None or entry.task_sequence < run.stop,
            )
            for entry in page.events
        ),
    )
    materializer = AgUiCheckpointMaterializer(store)
    transition = materializer.prepare_page(page, plan, scope, identity)
    assert transition is not None
    store.commit_projection_page(transition)
    return materializer, scope, page.events[3], identity, run


@pytest.mark.parametrize("fault", ["namespace", "version", "task", "source_segment"])
def test_whole_event_cursor_applies_same_identity_guards_as_partial_cursor(tmp_path, fault):
    materializer, scope, entry, identity, run = _observer_fixture(tmp_path / "whole.sqlite")
    if fault == "namespace":
        scope = replace(scope, namespace="foreign")
    elif fault == "version":
        scope = replace(scope, projector_version="unsupported-v2")
    elif fault == "task":
        entry = replace(entry, task_id=TaskId(uuid4()))
    else:
        entry = replace(entry, segment_id=SessionId(uuid4()))
    cursor = AgUiCursor(
        thread_id=identity.thread_id,
        run_id=identity.run_id,
        sequence=entry.task_sequence,
        event_id=str(entry.event.event_id),
        frame_index=0,
    )
    with pytest.raises(ValueError):
        list(materializer.iter_event_frames(scope, entry, identity, run=run, after=cursor))
    # Legacy tokens consume the whole Event, but may not erase scope/source
    # validation that the identical partial token already applies.
    whole = cursor.model_copy(update={"frame_index": None})
    with pytest.raises(ValueError):
        list(materializer.iter_event_frames(scope, entry, identity, run=run, after=whole))


@pytest.mark.parametrize("field", ["thread_id", "run_id", "event_id", "sequence", "frame_index"])
def test_exact_partial_cursor_mismatch_is_rejected(tmp_path, field):
    materializer, scope, entry, identity, run = _observer_fixture(tmp_path / "partial.sqlite")
    cursor = AgUiCursor(
        thread_id=identity.thread_id,
        run_id=identity.run_id,
        sequence=entry.task_sequence,
        event_id=str(entry.event.event_id),
        frame_index=0,
    )
    replacement = 99 if field in {"sequence", "frame_index"} else "foreign"
    with pytest.raises(ValueError):
        list(
            materializer.iter_event_frames(
                scope,
                entry,
                identity,
                run=run,
                after=cursor.model_copy(update={field: replacement}),
            )
        )


def test_checkpoint_head_read_is_consistent_with_concurrent_source_and_derived_append(tmp_path):
    database = tmp_path / "snapshot.sqlite"
    _scratch_schema(database)
    store, scope, events = _fixture(database)
    store.commit_projection_page(_transition(scope, events))
    writer = SQLiteAgentTaskStore(database)
    event_store = SQLiteEventStore(database)
    tail = _event(events[0].session_id, 3, EventType.SESSION_TITLE_UPDATED, {"title": "tail"})
    finished = Event()
    scheduled = False
    future = None

    def append():
        event_store.append(tail)
        head = writer.commit_projection_page(_transition(scope, (*events, tail), start=3))
        finished.set()
        return head

    # Interleave real append/CAS transactions immediately after the reader's
    # canonical highwater query, not forged rows or changes to old Events.
    with ThreadPoolExecutor(max_workers=1) as executor:

        class InterleavedConnection(sqlite3.Connection):
            def execute(self, sql, parameters=(), /):
                nonlocal scheduled, future
                if "SELECT * FROM task_projection_heads" in sql and not scheduled:
                    scheduled = True
                    future = executor.submit(append)
                    # A proper read snapshot may block the writer until this
                    # observation returns. Never force that correct case to hang.
                    finished.wait(0.2 if self.in_transaction else 5)
                return super().execute(sql, parameters)

        def connect():
            connection = sqlite3.connect(database, factory=InterleavedConnection)
            connection.row_factory = sqlite3.Row
            return connection

        store._database.connect = connect
        try:
            observed = store.read_checkpoint_head(scope)
        finally:
            assert scheduled and future is not None
            published = future.result(timeout=10)
        assert published.through_sequence == 3
        assert observed.through_sequence in {2, 3}
        assert observed.last_event_id == (*events, tail)[observed.through_sequence].event_id


@pytest.mark.parametrize("frame_index", [None, 0], ids=["whole", "partial"])
@pytest.mark.parametrize("window", ["stop", "frozen_highwater"])
def test_exact_cursor_rejects_event_outside_bound_run_window(tmp_path, frame_index, window):
    materializer, scope, entry, identity, run = _observer_fixture(
        tmp_path / "window.sqlite", bound=True
    )
    if window == "stop":
        entry = materializer.port.read_event_page(scope.task_id, run.stop - 1, limit=1).events[0]
    else:
        run = replace(run, highwater=entry.task_sequence - 1, stop=None)
    cursor = AgUiCursor(
        thread_id=identity.thread_id,
        run_id=identity.run_id,
        sequence=entry.task_sequence,
        event_id=str(entry.event.event_id),
        frame_index=frame_index,
    )
    with pytest.raises(ValueError, match="window"):
        list(materializer.iter_event_frames(scope, entry, identity, run=run, after=cursor))


def test_native_empty_sqlite_facade_initializes_replay_metadata(tmp_path):
    # No preparatory schema calls: this checks the facade integration separately.
    database = tmp_path / "native.sqlite"
    root = Session.create(title="Native scratch")
    SQLiteProjectionStore(database).save_session(root)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root.session_id)
    source = _event(
        root.session_id,
        0,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"kind": "run", "payload": {"run_id": "native-run"}},
    )
    SQLiteEventStore(database).append(source)
    run = store.read_run_header(task.task_id, "native-run")
    assert run.anchor is not None and run.anchor.event_id == source.event_id
    assert run.start == run.highwater == 0 and not run.legacy


@pytest.mark.parametrize("observation", ["port", "head_record"])
def test_terminal_locator_cannot_reference_a_zero_frame_watermark(tmp_path, observation):
    materializer, scope, _, _, _ = _observer_fixture(tmp_path / "terminal.sqlite")
    store = materializer.port
    head = store.read_checkpoint_head(scope)
    assert head.terminal is not None and head.terminal.frame_count > 0
    if observation == "head_record":
        with pytest.raises(ValueError):
            replace(head, terminal=replace(head.terminal, frame_count=0))
        return
    # Silent Events legitimately have zero frames, but cannot be the terminal
    # locator: this is the same invariant enforced by ProjectionTransition.
    with store._database.connect() as connection:
        connection.execute(
            "UPDATE task_projection_frames SET frame_count=0 WHERE task_sequence=?",
            (head.terminal.task_sequence,),
        )
    with pytest.raises(ValueError):
        store.read_checkpoint_head(scope)


@pytest.mark.parametrize("method", ["head", "frame", "scalar", "cells"])
@pytest.mark.parametrize("invalid_scope", [False, True], ids=["success", "failure"])
def test_checkpoint_read_snapshot_is_released_on_return_or_error(tmp_path, method, invalid_scope):
    materializer, scope, entry, _, _ = _observer_fixture(tmp_path / "read_exit.sqlite")
    store = materializer.port
    if invalid_scope:
        scope = replace(scope, namespace="foreign")
    connections, snapshots, statements = [], [], []

    class RecordingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            statements.append(sql)
            if sql.lstrip().upper().startswith("SELECT"):
                snapshots.append(self.in_transaction)
            return super().execute(sql, parameters)

    def connect():
        connection = sqlite3.connect(tmp_path / "read_exit.sqlite", factory=RecordingConnection)
        connection.row_factory = sqlite3.Row
        connections.append(connection)  # Keep alive: GC cannot hide a leaked snapshot.
        return connection

    store._database.connect = connect
    observations = {
        "head": lambda: store.read_checkpoint_head(scope),
        "frame": lambda: store.read_event_projection_header(scope, entry.task_sequence),
        "scalar": lambda: store.read_segment_checkpoint_before(
            scope, entry.segment_id, entry.task_sequence
        ),
        "cells": lambda: store.read_cells_at(
            scope, 5, (ProjectionCellKey(entry.segment_id, "tool_call", "tool-1"),)
        ),
    }
    try:
        if invalid_scope:
            with pytest.raises(CheckpointConflict):
                observations[method]()
        else:
            observations[method]()
        assert snapshots and all(snapshots)
        assert connections and all(not connection.in_transaction for connection in connections)
        assert not any(
            sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
        )
    finally:
        for connection in connections:
            connection.close()

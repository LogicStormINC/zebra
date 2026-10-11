"""Real SQLite storage: indexed observations and atomic, immutable page CAS."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import EventId, new_session_id
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCell,
    ProjectionCellKey,
    ProjectionFrameHeader,
    ProjectionScope,
    ProjectionTransition,
    SegmentCheckpoint,
)
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore


def _fixture(database: Path, count: int = 3):
    segment = new_session_id()
    events = tuple(
        SessionEvent.create(
            session_id=segment,
            sequence=position,
            actor=EventActor.SYSTEM,
            event_type=EventType.SESSION_CREATED
            if position == 0
            else EventType.SESSION_TITLE_UPDATED,
            payload={"title": f"Event {position}"},
        )
        for position in range(count)
    )
    event_store = SQLiteEventStore(database)
    for event in events:
        event_store.append(event)
    SQLiteProjectionStore(database).save_session(rebuild_session(list(events)))
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(segment)
    while not store.backfill_event_positions(task.task_id):
        pass
    scope = ProjectionScope("local", task.task_id, None, "test-v1")
    return store, scope, events


def _transition(scope, events, start=0, stop=None, *, cells=(), terminal=None):
    stop = len(events) if stop is None else stop
    return ProjectionTransition(
        scope,
        start - 1,
        tuple(
            ProjectionFrameHeader(
                position,
                event.event_id,
                event.session_id,
                event.sequence,
                position - 1,
                1,
                True,
                True,
            )
            for position, event in enumerate(events[start:stop], start)
        ),
        tuple(
            SegmentCheckpoint(event.session_id, position, event.sequence, True, False)
            for position, event in enumerate(events[start:stop], start)
        ),
        cells,
        terminal,
    )


def test_missing_head_is_observational_and_future_reads_are_explicit(tmp_path):
    store, scope, events = _fixture(tmp_path / "checkpoint.sqlite")
    statements = []
    connect = store._database.connect

    def traced():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    store._database.connect = traced
    assert store.read_checkpoint_head(scope).through_sequence == -1
    assert store.read_segment_checkpoint_before(scope, events[0].session_id, 0).task_sequence == -1
    assert store.read_cells_at(scope, 0, ()) == ()
    with pytest.raises(CheckpointNotReady):
        store.read_event_projection_header(scope, 0)
    with pytest.raises(CheckpointNotReady):
        store.read_segment_checkpoint_before(scope, events[0].session_id, 1)
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
    )
    assert not any("payload" in sql for sql in statements)


def test_page_commit_restores_strict_predecessors_and_tombstones(tmp_path):
    store, scope, events = _fixture(tmp_path / "checkpoint.sqlite")
    key = ProjectionCellKey(events[0].session_id, "tool_call", "tool-1")
    first = _transition(
        scope,
        events,
        stop=2,
        cells=(
            ProjectionCell(key, 0, "1"),
            ProjectionCell(key, 1, None),
        ),
    )
    head = store.commit_projection_page(first)
    assert head.through_sequence == 1 and head.last_event_id == events[1].event_id
    assert store.read_cells_at(scope, 1, (key,)) == (ProjectionCell(key, 0, "1"),)
    assert store.read_cells_at(scope, 2, (key,)) == (ProjectionCell(key, 1, None),)
    assert store.read_segment_checkpoint_before(scope, key.segment_id, 1).task_sequence == 0
    assert store.read_event_projection_header(scope, 1).state_before_sequence == 0
    second = _transition(scope, events, start=2, terminal=2)
    assert store.commit_projection_page(second).terminal.task_sequence == 2


def test_duplicate_commit_cannot_overwrite_published_page(tmp_path):
    store, scope, events = _fixture(tmp_path / "checkpoint.sqlite")
    transition = _transition(scope, events)
    expected = store.commit_projection_page(transition)
    with pytest.raises(CheckpointConflict, match="CAS"):
        store.commit_projection_page(transition)
    assert store.read_checkpoint_head(scope) == expected


def test_concurrent_observers_publish_one_page_without_partial_state(tmp_path):
    store, scope, events = _fixture(tmp_path / "checkpoint.sqlite")
    transition = _transition(scope, events)

    def submit():
        try:
            return store.commit_projection_page(transition).through_sequence
        except CheckpointConflict:
            return "lost-CAS"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert sorted(results, key=str) == [2, "lost-CAS"]
    with store._database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM task_projection_frames").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM task_projection_scalars").fetchone()[0] == 3


@pytest.mark.parametrize("conflict", ["source", "predecessor"])
def test_failed_commit_rolls_back_head_and_every_derived_row(tmp_path, conflict):
    store, scope, events = _fixture(tmp_path / "checkpoint.sqlite")
    transition = _transition(scope, events)
    headers = list(transition.headers)
    headers[1] = replace(
        headers[1],
        **(
            {"event_id": EventId(uuid4())}
            if conflict == "source"
            else {"state_before_sequence": -1}
        ),
    )
    transition = replace(transition, headers=tuple(headers))
    with pytest.raises(CheckpointConflict):
        store.commit_projection_page(transition)
    assert store.read_checkpoint_head(scope).through_sequence == -1
    with store._database.connect() as connection:
        for table in ("heads", "frames", "scalars", "cells"):
            assert (
                connection.execute(f"SELECT count(*) FROM task_projection_{table}").fetchone()[0]
                == 0
            )


def test_scope_version_and_anchor_are_isolated(tmp_path):
    store, scope, events = _fixture(tmp_path / "checkpoint.sqlite")
    store.commit_projection_page(_transition(scope, events))
    other_version = replace(scope, projector_version="test-v2")
    other_anchor = replace(scope, anchor_event_id=events[0].event_id)
    assert store.read_checkpoint_head(other_version).through_sequence == -1
    assert store.read_checkpoint_head(other_anchor).through_sequence == -1
    with pytest.raises(CheckpointConflict, match="namespace"):
        store.read_checkpoint_head(replace(scope, namespace="foreign"))
    with pytest.raises(CheckpointConflict, match="anchor"):
        store.read_checkpoint_head(replace(scope, anchor_event_id=EventId(uuid4())))


def test_foreign_segment_reads_fail_instead_of_looking_like_empty_state(tmp_path):
    store, scope, _ = _fixture(tmp_path / "checkpoint.sqlite")
    foreign = new_session_id()
    with pytest.raises(CheckpointConflict, match="Segment"):
        store.read_segment_checkpoint_before(scope, foreign, 0)
    with pytest.raises(CheckpointConflict, match="Segment"):
        store.read_cells_at(scope, 0, (ProjectionCellKey(foreign, "tool_call", "call"),))


def test_silent_headers_advance_frontier_without_resetting_segment_state(tmp_path):
    store, scope, events = _fixture(tmp_path / "checkpoint.sqlite")
    first = _transition(scope, events, stop=1)
    store.commit_projection_page(first)
    transition = ProjectionTransition(
        scope,
        0,
        tuple(
            ProjectionFrameHeader(p, e.event_id, e.session_id, e.sequence, -1, 0, False, False)
            for p, e in enumerate(events[1:], 1)
        ),
        (),
        (),
    )
    head = store.commit_projection_page(transition)
    assert head.through_sequence == 2 and head.latest_eligible.task_sequence == 0
    assert store.read_segment_checkpoint_before(scope, events[0].session_id, 3).task_sequence == 0


def test_key_byte_admission_precedes_loading_values(tmp_path):
    store, scope, events = _fixture(tmp_path / "checkpoint.sqlite", 2)
    keys = tuple(
        ProjectionCellKey(events[0].session_id, "text_message", f"call-{n}") for n in range(100)
    )
    for position in range(2):
        cells = tuple(
            ProjectionCell(k, position, "x" * 2048)
            for k in keys[position * 50 : (position + 1) * 50]
        )
        store.commit_projection_page(
            _transition(scope, events, position, position + 1, cells=cells)
        )
    statements = []
    connect = store._database.connect

    def traced():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    store._database.connect = traced
    with pytest.raises(ValueError, match="byte bound"):
        store.read_cells_at(scope, 2, keys)
    assert not any("SELECT value FROM" in sql for sql in statements)


def test_exact_cell_seek_uses_primary_index(tmp_path):
    store, scope, events = _fixture(tmp_path / "checkpoint.sqlite")
    with store._database.connect() as connection:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT task_sequence,byte_count FROM task_projection_cells "
            "WHERE deployment_namespace=? AND task_id=? AND anchor_key=? AND projector_version=? "
            "AND segment_id=? AND cell_kind=? AND cell_key=? AND task_sequence<? "
            "ORDER BY task_sequence DESC LIMIT 1",
            (
                scope.namespace,
                str(scope.task_id),
                "",
                scope.projector_version,
                str(events[0].session_id),
                "tool_call",
                "call",
                100000,
            ),
        ).fetchall()
    assert any("SEARCH" in row[3] and "task_sequence<?" in row[3] for row in plan)
    assert not any("TEMP B-TREE" in row[3] or "SCAN" in row[3] for row in plan)

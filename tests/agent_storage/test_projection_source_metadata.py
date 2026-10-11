"""Source-owned blocks and causal scalar handoffs, including cold indexed reads."""

import json
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_storage.database import SQLiteDatabase
from agent_storage.projection_source_metadata import (
    SQLiteProjectionSourceMetadataMixin,
    backfill_projection_source_metadata,
    write_projection_source_metadata,
)
from agent_storage.projection_source_metadata_schema import initialize_projection_source_metadata

NS = "projection-metadata"


class Store(SQLiteProjectionSourceMetadataMixin):
    def __init__(self, path: Path) -> None:
        self._database = SQLiteDatabase(path)


def database(
    path: Path, count: int = 0, *, install: bool = True
) -> tuple[sqlite3.Connection, TaskId, SessionId, SessionId]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE session_events(event_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,
          sequence INTEGER NOT NULL,event_type TEXT NOT NULL,
          payload TEXT NOT NULL,actor TEXT NOT NULL,
          task_id TEXT,task_sequence INTEGER,UNIQUE(session_id,sequence));
        CREATE UNIQUE INDEX session_events_task_positions ON session_events(task_id,task_sequence);
        CREATE TABLE agent_tasks(task_id TEXT PRIMARY KEY,namespace TEXT,
          next_event_sequence INTEGER,event_position_state TEXT);
        CREATE TABLE execution_segments(session_id TEXT PRIMARY KEY,task_id TEXT,
          event_position_source_ready INTEGER,event_position_source_cursor INTEGER);
    """)
    task, a, b = TaskId(uuid4()), SessionId(uuid4()), SessionId(uuid4())
    connection.execute("INSERT INTO agent_tasks VALUES (?,?,?,'ready')", (str(task), NS, count))
    for segment in (a, b):
        connection.execute(
            "INSERT INTO execution_segments VALUES (?,?,1,-1)", (str(segment), str(task))
        )
    connection.commit()
    if install:
        initialize_projection_source_metadata(connection)
    return connection, task, a, b


def append(
    connection: sqlite3.Connection,
    task: TaskId,
    segment: SessionId,
    sequence: int,
    *,
    kind: str = "session_title_updated",
    handoff: UUID | None = None,
    peer: SessionId | None = None,
) -> EventId:
    row = connection.execute(
        "SELECT next_event_sequence FROM agent_tasks WHERE task_id=?", (str(task),)
    ).fetchone()
    assert row is not None
    event = EventId(uuid4())
    payload = (
        {"title": "metadata"}
        if handoff is None
        else {
            "handoff_id": str(handoff),
            "target_session_id"
            if kind == "session_handoff_committed"
            else "parent_session_id": str(peer),
        }
    )
    connection.execute(
        "INSERT INTO session_events(event_id,session_id,sequence,event_type,payload,actor) "
        "VALUES (?,?,?,?,?,'system')",
        (str(event), str(segment), sequence, kind, json.dumps(payload)),
    )
    connection.execute(
        "UPDATE agent_tasks SET next_event_sequence=next_event_sequence+1 WHERE task_id=?",
        (str(task),),
    )
    connection.execute(
        "UPDATE session_events SET task_id=?,task_sequence=? WHERE event_id=?",
        (str(task), row[0], str(event)),
    )
    connection.execute(
        "UPDATE execution_segments SET event_position_source_cursor=? WHERE session_id=?",
        (sequence, str(segment)),
    )
    return event


def test_native_blocks_revisit_and_snapshot_clip(tmp_path: Path) -> None:
    path = tmp_path / "blocks.sqlite"
    connection, task, a, b = database(path)
    for segment, seq in ((a, 0), (a, 1), (b, 0), (b, 1), (a, 2), (a, 3)):
        append(connection, task, segment, seq)
    connection.commit()
    store = Store(path)
    block = store.read_projection_block(task, 5, through_sequence=5)
    assert (
        block.segment_id,
        block.first_task_sequence,
        block.last_task_sequence,
        block.first_segment_sequence,
        block.last_segment_sequence,
        block.previous_block_start,
    ) == (a, 4, 5, 2, 3, 0)
    assert store.read_projection_block(task, 4, through_sequence=4).last_task_sequence == 4
    assert store.read_projection_block(task, 2, through_sequence=5).previous_block_start is None


def test_latest_commit_is_strict_not_peer_filtered(tmp_path: Path) -> None:
    path = tmp_path / "handoff.sqlite"
    connection, task, a, b = database(path)
    handoff = uuid4()
    append(connection, task, a, 0, kind="session_handoff_committed", handoff=handoff, peer=b)
    append(
        connection,
        task,
        a,
        1,
        kind="session_handoff_committed",
        handoff=handoff,
        peer=SessionId(uuid4()),
    )
    append(connection, task, b, 0, kind="session_handoff_received", handoff=handoff, peer=a)
    connection.commit()
    store = Store(path)
    older = store.read_latest_handoff_commit(task, a, handoff, 1, through_sequence=2)
    newer = store.read_latest_handoff_commit(task, a, handoff, 2, through_sequence=2)
    assert older is not None and older.source.task_sequence == 0 and older.peer_segment_id == b
    assert newer is not None and newer.source.task_sequence == 1 and newer.peer_segment_id != b
    assert len(store.read_handoff_receives(task, b, through_sequence=2)) == 1


def test_receive_readiness_missing_duplicate_and_valid(tmp_path: Path) -> None:
    path = tmp_path / "receives.sqlite"
    connection, task, a, b = database(path)
    handoff = uuid4()
    append(connection, task, a, 0, kind="session_handoff_committed", handoff=handoff, peer=b)
    append(connection, task, b, 0, kind="session_handoff_received", handoff=handoff, peer=a)
    connection.commit()
    store = Store(path)
    assert len(store.read_handoff_receives(task, b, through_sequence=1)) == 1
    assert store.read_handoff_receives(task, a, through_sequence=1) == ()
    assert store.read_latest_handoff_commit(task, a, handoff, 0, through_sequence=1) is None
    append(connection, task, b, 1, kind="session_handoff_received", handoff=handoff, peer=a)
    connection.commit()
    with pytest.raises(CheckpointConflict, match="ambiguous"):
        store.read_handoff_receives(task, b, through_sequence=2)
    assert len(store.read_handoff_receives(task, b, through_sequence=1)) == 1


def test_bounded_legacy_repair_and_frozen_cycle(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    connection, task, a, _ = database(path, 600, install=False)
    for start in range(0, 600, 256):
        connection.executemany(
            "INSERT INTO session_events VALUES (?,?,?,'session_title_updated','{}','system',?,?)",
            [(str(uuid4()), str(a), n, str(task), n) for n in range(start, min(start + 256, 600))],
        )
    connection.execute(
        "UPDATE execution_segments SET event_position_source_cursor=599 WHERE session_id=?",
        (str(a),),
    )
    connection.commit()
    initialize_projection_source_metadata(connection)
    with pytest.raises(CheckpointNotReady, match="explicit backfill"):
        Store(path).read_projection_block(task, 0, through_sequence=599)
    assert not backfill_projection_source_metadata(connection, NS, task, limit=256)
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM session_events WHERE projection_metadata_ready=1"
        ).fetchone()[0]
        == 256
    )
    connection.commit()
    connection.close()
    with sqlite3.connect(path) as resumed:
        resumed.row_factory = sqlite3.Row
        assert not backfill_projection_source_metadata(resumed, NS, task)
        resumed.commit()
        append(resumed, task, a, 600)
        resumed.commit()
        assert backfill_projection_source_metadata(resumed, NS, task)
        assert tuple(
            resumed.execute(
                "SELECT repair_cursor,repair_highwater FROM task_projection_source_heads"
            ).fetchone()
        ) == (-1, -1)
    assert (
        Store(path).read_projection_block(task, 599, through_sequence=599).last_task_sequence == 599
    )
    with pytest.raises(ValueError, match="not ready|missing coverage"):
        Store(path).read_projection_block(task, 600, through_sequence=600)


def test_explicit_block_hole_repair_and_conflict(tmp_path: Path) -> None:
    path = tmp_path / "repair.sqlite"
    connection, task, a, _ = database(path)
    event = append(connection, task, a, 0)
    append(connection, task, a, 1)
    connection.commit()
    connection.execute("DELETE FROM task_projection_blocks")
    connection.commit()
    with pytest.raises(ValueError, match="conflicts"):
        Store(path).read_projection_block(task, 0, through_sequence=1)
    write_projection_source_metadata(connection, NS, event)
    connection.commit()
    assert Store(path).read_projection_block(task, 0, through_sequence=1).last_task_sequence == 1
    connection.execute(
        "UPDATE task_projection_blocks SET last_task_sequence=0,last_segment_sequence=0"
    )
    connection.commit()
    with pytest.raises(CheckpointConflict, match="range conflicts"):
        Store(path).read_projection_block(task, 0, through_sequence=1)
    with pytest.raises(ValueError, match="conflicts with source"):
        write_projection_source_metadata(connection, NS, event)


@pytest.mark.parametrize(
    "field,value",
    [("projection_handoff_id", "NULL"), ("projection_block_start", "1"), ("payload", "'{}'")],
)
def test_source_metadata_immutable(tmp_path: Path, field: str, value: str) -> None:
    connection, task, a, b = database(tmp_path / "immutable.sqlite")
    event = append(
        connection, task, a, 0, kind="session_handoff_committed", handoff=uuid4(), peer=b
    )
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="immutable|conflicts"):
        connection.execute(
            f"UPDATE session_events SET {field}={value} WHERE event_id=?", (str(event),)
        )


@pytest.mark.parametrize("count", [1000, 10000, 100000])
def test_cold_reads_are_indexed_and_payload_forbidden(tmp_path: Path, count: int) -> None:
    path = tmp_path / "cold.sqlite"
    connection, task, a, b = database(path, count, install=False)
    handoff = uuid4()
    for start in range(0, count, 256):
        connection.executemany(
            "INSERT INTO session_events VALUES (?,?,?,'session_title_updated','{}','system',?,?)",
            [
                (str(uuid4()), str(a), n, str(task), n)
                for n in range(start, min(start + 256, count))
            ],
        )
    connection.execute(
        "UPDATE execution_segments SET event_position_source_cursor=? WHERE session_id=?",
        (count - 1, str(a)),
    )
    connection.commit()
    initialize_projection_source_metadata(connection)
    while not backfill_projection_source_metadata(connection, NS, task):
        connection.commit()
    append(connection, task, a, count, kind="session_handoff_committed", handoff=handoff, peer=b)
    append(connection, task, b, 0, kind="session_handoff_received", handoff=handoff, peer=a)
    connection.commit()
    connection.close()
    statements: list[str] = []

    class Protected(SQLiteDatabase):
        def connect(self) -> sqlite3.Connection:
            connection = super().connect()
            connection.set_authorizer(
                lambda action, table, column, *_: sqlite3.SQLITE_DENY
                if (
                    action == sqlite3.SQLITE_READ
                    and table == "session_events"
                    and column == "payload"
                )
                else sqlite3.SQLITE_OK
            )
            connection.set_trace_callback(statements.append)
            return connection

    store = Store(path)
    store._database = Protected(path)
    assert (
        store.read_projection_block(task, count - 1, through_sequence=count + 1).last_task_sequence
        == count
    )
    assert len(store.read_handoff_receives(task, b, through_sequence=count + 1)) == 1
    commit = store.read_latest_handoff_commit(
        task, a, handoff, count + 1, through_sequence=count + 1
    )
    assert commit is not None and commit.source.task_sequence == count
    with sqlite3.connect(path) as proof:
        plans = [
            row[3]
            for statement in statements
            if statement.startswith("SELECT")
            for row in proof.execute("EXPLAIN QUERY PLAN " + statement)
        ]
    assert not any("SCAN " in plan or "TEMP B-TREE" in plan for plan in plans), plans
    assert any("session_events_projection_receive" in plan for plan in plans)
    assert any("session_events_projection_commit" in plan for plan in plans)


def test_budget_namespace_and_foreign_segment_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "trust.sqlite"
    connection, task, a, _ = database(path)
    append(connection, task, a, 0)
    connection.commit()
    store = Store(path)
    for limit in (0, 257, True):
        with pytest.raises(ValueError, match="limit"):
            store.read_handoff_receives(task, a, through_sequence=0, limit=limit)
    with pytest.raises(ValueError, match="another Task"):
        store.read_handoff_receives(task, SessionId(uuid4()), through_sequence=0)
    with pytest.raises(ValueError, match="namespace"):
        backfill_projection_source_metadata(connection, "wrong", task)
    with pytest.raises(ValueError, match="highwater"):
        store.read_projection_block(task, 0, through_sequence=1)


def test_orphan_receive_is_not_pending_metadata(tmp_path: Path) -> None:
    path = tmp_path / "orphan.sqlite"
    connection, task, a, b = database(path)
    handoff = uuid4()
    append(connection, task, b, 0, kind="session_handoff_received", handoff=handoff, peer=a)
    connection.commit()
    store = Store(path)
    assert len(store.read_handoff_receives(task, b, through_sequence=0)) == 1
    assert store.read_latest_handoff_commit(task, a, handoff, 1, through_sequence=0) is None
    connection.execute(
        "UPDATE execution_segments SET event_position_source_ready=0 WHERE session_id=?", (str(a),)
    )
    connection.commit()
    with pytest.raises(CheckpointNotReady, match="Segment is not ready"):
        store.read_latest_handoff_commit(task, a, handoff, 1, through_sequence=0)


def test_core_records_reject_noncontiguous_or_untyped_coordinates() -> None:
    from agent_core.ports.task_replay import TaskProjectionBlock

    task, segment = TaskId(uuid4()), SessionId(uuid4())
    for coordinates in (
        (0, 1, 0, 0, None),
        (0, 0, 1, 1, None),
        (True, 1, 0, 1, None),
        (0, 2**63, 0, 2**63, None),
        (2, 2, 1, 1, 2),
    ):
        with pytest.raises(ValueError):
            TaskProjectionBlock(task, segment, *coordinates)


def test_whole_block_requires_source_cursor_coverage(tmp_path: Path) -> None:
    path = tmp_path / "coverage.sqlite"
    connection, task, a, _ = database(path)
    append(connection, task, a, 0)
    append(connection, task, a, 1)
    connection.execute(
        "UPDATE execution_segments SET event_position_source_cursor=0 WHERE session_id=?", (str(a),)
    )
    connection.commit()
    with pytest.raises(CheckpointConflict, match="source coverage"):
        Store(path).read_projection_block(task, 0, through_sequence=1)
    assert Store(path).read_projection_block(task, 0, through_sequence=0).last_segment_sequence == 0


def test_multi_select_read_is_one_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.sqlite"
    connection, task, a, _ = database(path)
    connection.execute("PRAGMA journal_mode=WAL")
    append(connection, task, a, 0)
    connection.commit()
    mutated = False

    class SnapshotConnection(sqlite3.Connection):
        def execute(self, query: str, parameters: object = (), /) -> sqlite3.Cursor:
            nonlocal mutated
            cursor = super().execute(query, parameters)  # type: ignore[arg-type]
            if query.startswith("SELECT namespace") and not mutated:
                mutated = True
                with sqlite3.connect(path) as writer:
                    writer.execute("DELETE FROM task_projection_blocks")
            return cursor

    class SnapshotDatabase(SQLiteDatabase):
        def connect(self) -> sqlite3.Connection:
            reader = sqlite3.connect(path, factory=SnapshotConnection)
            reader.row_factory = sqlite3.Row
            return reader

    store = Store(path)
    store._database = SnapshotDatabase(path)
    assert store.read_projection_block(task, 0, through_sequence=0).segment_id == a
    assert mutated
    with pytest.raises(CheckpointConflict):
        Store(path).read_projection_block(task, 0, through_sequence=0)


def test_real_sqlite_task_allocator_and_explicit_activation(tmp_path: Path) -> None:
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore

    path, root = tmp_path / "production.sqlite", SessionId(uuid4())
    events = SQLiteEventStore(path)
    first = SessionEvent.create(
        session_id=root,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "source metadata"},
    )
    events.append(first)
    SQLiteProjectionStore(path).save_session(rebuild_session([first]))
    SQLiteAgentTaskStore(path).ensure_for_session(root)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        initialize_projection_source_metadata(connection)
        assert backfill_projection_source_metadata(connection, "local", TaskId(root))
    events.append(
        SessionEvent.create(
            session_id=root,
            sequence=1,
            event_type=EventType.SESSION_TITLE_UPDATED,
            actor=EventActor.SYSTEM,
            payload={"title": "late"},
        )
    )
    assert (
        Store(path).read_projection_block(TaskId(root), 1, through_sequence=1).last_segment_sequence
        == 1
    )

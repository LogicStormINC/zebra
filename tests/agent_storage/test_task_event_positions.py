"""Source coordinates stay fixed even when the derived index is repaired."""

import sqlite3
from pathlib import Path

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore
from agent_storage.database import SQLiteDatabase
from agent_storage.task_event_positions import repair_task_event_index


def _seed(database: Path, *, count: int = 1) -> SessionId:
    session = new_session_id()
    events = SQLiteEventStore(database)
    history = [
        SessionEvent.create(
            session_id=session,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Positions"},
        )
    ]
    for sequence in range(1, count):
        history.append(_title(session, sequence))
    for event in history:
        events.append(event)
    SQLiteProjectionStore(database).save_session(rebuild_session(history))
    return session


def _title(session: SessionId, sequence: int) -> SessionEvent:
    return SessionEvent.create(
        session_id=session,
        sequence=sequence,
        event_type=EventType.SESSION_TITLE_UPDATED,
        actor=EventActor.SYSTEM,
        payload={"title": f"Title {sequence}"},
    )


def test_late_predecessor_event_appends_without_rewriting_the_prefix(tmp_path: Path) -> None:
    database = tmp_path / "positions.sqlite"
    root, child = _seed(database), _seed(database)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root)
    store.attach_segment(task.task_id, child, predecessor_id=root, reason=RolloverReason.RECOVERY)
    before = store.read_events(task.task_id, -1)
    late = _title(root, 1)
    SQLiteEventStore(database).append(late)
    after = store.read_events(task.task_id, -1)
    assert after[:-1] == before
    assert after[-1].event == late
    assert after[-1].task_sequence == len(before)
    assert [item.segment_id for item in after] == [root, child, root]


def test_missing_index_cell_is_restored_from_source_without_new_coordinates(tmp_path: Path) -> None:
    database = tmp_path / "positions.sqlite"
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(_seed(database, count=4))
    before = store.read_events(task.task_id, -1)
    with SQLiteDatabase(database).connect() as connection:
        connection.execute("DELETE FROM task_event_index WHERE task_sequence=1")
    assert store.read_events(task.task_id, -1) == before
    with SQLiteDatabase(database).connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        assert repair_task_event_index(connection, task.task_id) == 1
        assert repair_task_event_index(connection, task.task_id) == 0
        assert [
            row[0]
            for row in connection.execute(
                "SELECT task_sequence FROM task_event_index ORDER BY task_sequence"
            )
        ] == [0, 1, 2, 3]
    assert store.read_events(task.task_id, -1) == before


@pytest.mark.parametrize(
    "column,value",
    [
        ("task_sequence", 99),
        ("task_id", "foreign"),
        ("sequence", 99),
    ],
)
def test_source_coordinates_and_identity_cannot_be_reassigned(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    database = tmp_path / "positions.sqlite"
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(_seed(database))
    before = store.read_events(task.task_id, -1)
    with (
        SQLiteDatabase(database).connect() as connection,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        connection.execute(f"UPDATE session_events SET {column}=?", (value,))
    assert store.read_events(task.task_id, -1) == before


def test_conflicting_index_cell_fails_closed_instead_of_renumbering(tmp_path: Path) -> None:
    database = tmp_path / "positions.sqlite"
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(_seed(database, count=2))
    before = store.read_events(task.task_id, -1)
    with SQLiteDatabase(database).connect() as connection:
        connection.execute("UPDATE task_event_index SET task_sequence=9 WHERE task_sequence=1")
    with (
        SQLiteDatabase(database).connect() as connection,
        pytest.raises(ValueError, match="conflicts with source"),
    ):
        connection.execute("BEGIN IMMEDIATE")
        repair_task_event_index(connection, task.task_id)
    assert store.read_events(task.task_id, -1) == before


def test_rolled_back_source_append_does_not_leave_a_position_gap(tmp_path: Path) -> None:
    database = tmp_path / "positions.sqlite"
    root = _seed(database)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root)
    with SQLiteDatabase(database).connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO session_events
               (event_id,session_id,sequence,event_type,payload,actor,created_at)
               SELECT 'rolled-back',session_id,1,event_type,payload,actor,created_at
               FROM session_events WHERE sequence=0"""
        )
        connection.rollback()
    SQLiteEventStore(database).append(_title(root, 1))
    assert [item.task_sequence for item in store.read_events(task.task_id, -1)] == [0, 1]


def test_legacy_backfill_is_bounded_resumable_and_blocks_new_source_appends(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite"
    root = _seed(database, count=600)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root)
    with SQLiteDatabase(database).connect() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM session_events WHERE task_id IS NOT NULL"
            ).fetchone()[0]
            == 256
        )
    with pytest.raises(ValueError, match="explicit backfill"):
        store.read_events(task.task_id, -1)
    with pytest.raises(ValueError):
        SQLiteEventStore(database).append(_title(root, 600))
    assert not store.backfill_event_positions(task.task_id)
    assert store.backfill_event_positions(task.task_id)
    assert len(store.read_events(task.task_id, -1)) == 600
    assert store.backfill_event_positions(task.task_id)
    SQLiteEventStore(database).append(_title(root, 600))
    assert store.read_events(task.task_id, -1)[-1].task_sequence == 600


def test_already_positioned_child_cannot_be_reparented(tmp_path: Path) -> None:
    database = tmp_path / "positions.sqlite"
    root, child = _seed(database), _seed(database)
    store = SQLiteAgentTaskStore(database)
    root_task, child_task = store.ensure_for_session(root), store.ensure_for_session(child)
    before = store.read_events(child_task.task_id, -1)
    with pytest.raises(ValueError):
        store.attach_segment(
            root_task.task_id, child, predecessor_id=root, reason=RolloverReason.RECOVERY
        )
    assert store.read_events(child_task.task_id, -1) == before
    assert store.active_segment(root_task.task_id) == root


def test_large_child_adoption_commits_progress_and_resumes_without_reattaching(
    tmp_path: Path,
) -> None:
    database = tmp_path / "positions.sqlite"
    root, child = _seed(database), _seed(database, count=600)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root)
    assert store.backfill_replay_headers(task.task_id, limit=1)
    original = store.read_event_header(task.task_id, 0)
    attached = store.attach_segment(
        task.task_id, child, predecessor_id=root, reason=RolloverReason.RECOVERY
    )
    assert attached.active_segment_id == child
    with store._database.connect() as connection:
        assert tuple(
            connection.execute(
                "SELECT event_position_state,next_event_sequence FROM agent_tasks WHERE task_id=?",
                (str(task.task_id),),
            ).fetchone()
        ) == ("assigning", 257)
        assert (
            connection.execute(
                "SELECT count(*) FROM session_events WHERE session_id=? AND task_id IS NOT NULL",
                (str(child),),
            ).fetchone()[0]
            == 256
        )
    with pytest.raises(ValueError, match="explicit backfill"):
        store.read_event_page(task.task_id, -1)
    with pytest.raises(ValueError) as blocked:
        SQLiteEventStore(database).append(_title(child, 600))
    assert isinstance(blocked.value.__cause__, sqlite3.IntegrityError)
    assert "explicit backfill" in str(blocked.value.__cause__)
    assert not store.backfill_event_positions(task.task_id)
    assert store.backfill_event_positions(task.task_id)
    assert store.read_event_header(task.task_id, 0) == original
    last = store.read_event_page(task.task_id, 598)
    assert [item.task_sequence for item in last.events] == [599, 600]
    assert last.events[-1].segment_sequence == 599
    SQLiteEventStore(database).append(_title(child, 600))
    assert store.read_event_header(task.task_id, 601).segment_sequence == 600


@pytest.mark.parametrize("positions", [[0, 2, 1], [0, 2, 3]])
def test_prepositioned_legacy_events_still_require_contiguous_source_order(
    tmp_path: Path,
    positions: list[int],
) -> None:
    database = tmp_path / "legacy.sqlite"
    root = _seed(database, count=3)
    store = SQLiteAgentTaskStore(database)
    with SQLiteDatabase(database).connect() as connection:
        for sequence, position in enumerate(positions):
            connection.execute(
                "UPDATE session_events SET task_id=?,task_sequence=? WHERE sequence=?",
                (str(root), position, sequence),
            )
    with pytest.raises(ValueError):
        store.ensure_for_session(root)


def test_prepositioned_foreign_tail_cannot_disappear_during_adoption(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite"
    root = _seed(database, count=3)
    store = SQLiteAgentTaskStore(database)
    with SQLiteDatabase(database).connect() as connection:
        connection.execute(
            "UPDATE session_events SET task_id='foreign',task_sequence=0 WHERE sequence=2"
        )
    with pytest.raises(ValueError, match="another Task"):
        store.ensure_for_session(root)


def test_source_backed_legacy_index_hole_is_adopted_without_renumbering(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite"
    root = _seed(database, count=3)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root)
    before = store.read_events(task.task_id, -1)
    with SQLiteDatabase(database).connect() as connection:
        connection.execute("DELETE FROM task_event_index WHERE task_sequence=0")
        connection.execute(
            "UPDATE agent_tasks SET event_position_state='legacy',event_position_cursor=-1"
        )
    assert store.backfill_event_positions(task.task_id)
    assert store.read_events(task.task_id, -1) == before


def test_repair_budget_bounds_examined_positions_not_only_changed_rows(tmp_path: Path) -> None:
    database = tmp_path / "positions.sqlite"
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(_seed(database, count=4))
    with SQLiteDatabase(database).connect() as connection:
        connection.execute("DELETE FROM task_event_index WHERE task_sequence=3")
    for expected_cursor in (0, 1, 2):
        with SQLiteDatabase(database).connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            assert repair_task_event_index(connection, task.task_id, limit=1) == 0
            assert (
                connection.execute("SELECT event_index_repair_cursor FROM agent_tasks").fetchone()[
                    0
                ]
                == expected_cursor
            )
    with SQLiteDatabase(database).connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        assert repair_task_event_index(connection, task.task_id, limit=1) == 1


def test_unvalidated_legacy_reservations_are_frozen_between_batches(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite"
    root = _seed(database, count=600)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root)
    with SQLiteDatabase(database).connect() as connection:
        # An unmapped tail cannot acquire a new legacy reservation after adoption started.
        with pytest.raises(sqlite3.IntegrityError, match="reservation"):
            connection.execute(
                """INSERT INTO task_event_index
                   SELECT ?,400,event_id,session_id,sequence
                   FROM session_events WHERE sequence=500""",
                (str(task.task_id),),
            )
        with pytest.raises(sqlite3.IntegrityError, match="reservation"):
            connection.execute("DELETE FROM task_event_index WHERE task_sequence=0")


def test_source_append_cannot_skip_a_session_position(tmp_path: Path) -> None:
    database = tmp_path / "positions.sqlite"
    root = _seed(database)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root)
    with pytest.raises(ValueError):
        SQLiteEventStore(database).append(_title(root, 2))
    assert [item.task_sequence for item in store.read_events(task.task_id, -1)] == [0]


def test_repair_cycle_revisits_old_holes_under_continuous_appends(tmp_path: Path) -> None:
    database = tmp_path / "positions.sqlite"
    root = _seed(database, count=3)
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root)
    with SQLiteDatabase(database).connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        repair_task_event_index(connection, task.task_id, limit=1)
        connection.execute("DELETE FROM task_event_index WHERE task_sequence=0")
    for sequence in range(3, 12):
        SQLiteEventStore(database).append(_title(root, sequence))
        with SQLiteDatabase(database).connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            repair_task_event_index(connection, task.task_id, limit=1)
    with SQLiteDatabase(database).connect() as connection:
        assert (
            connection.execute("SELECT 1 FROM task_event_index WHERE task_sequence=0").fetchone()
            is not None
        )


def test_assigned_legacy_source_cannot_be_deleted_before_membership(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite"
    root = _seed(database, count=3)
    SQLiteAgentTaskStore(database)
    with SQLiteDatabase(database).connect() as connection:
        for sequence in range(3):
            connection.execute(
                "UPDATE session_events SET task_id=?,task_sequence=? WHERE sequence=?",
                (str(root), sequence, sequence),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM session_events WHERE sequence=2")

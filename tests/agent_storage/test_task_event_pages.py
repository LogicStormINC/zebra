"""Real seek pages cap hydrated bodies, preserve a highwater and fail closed."""

from pathlib import Path

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore
from agent_storage.database import SQLiteDatabase


def _task(database: Path, count: int):
    session = new_session_id()
    events = [
        SessionEvent.create(
            session_id=session,
            sequence=sequence,
            actor=EventActor.SYSTEM,
            event_type=EventType.SESSION_CREATED
            if sequence == 0
            else EventType.SESSION_TITLE_UPDATED,
            payload={"title": f"Title {sequence}"},
        )
        for sequence in range(count)
    ]
    event_store = SQLiteEventStore(database)
    for event in events:
        event_store.append(event)
    SQLiteProjectionStore(database).save_session(rebuild_session(events))
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(session)
    while not store.backfill_event_positions(task.task_id):
        pass
    return store, task


def test_seek_page_materializes_only_the_requested_bodies(tmp_path: Path, monkeypatch) -> None:
    from agent_storage import task_event_pages

    store, task = _task(tmp_path / "pages.sqlite", 1000)
    decoded = []
    original = task_event_pages.deserialize_event_row

    def counted(row):
        decoded.append(row["task_sequence"])
        return original(row)

    monkeypatch.setattr(task_event_pages, "deserialize_event_row", counted)
    page = store.read_event_page(task.task_id, 500, limit=3)
    assert decoded == [501, 502, 503]
    assert [entry.task_sequence for entry in page.events] == decoded
    assert page.after_sequence == 500 and page.next_sequence == 503
    assert page.highwater == 999 and page.has_more
    assert 0 < page.byte_count <= 1_048_576


def test_seek_page_retains_its_captured_highwater_across_appends(tmp_path: Path) -> None:
    database = tmp_path / "pages.sqlite"
    store, task = _task(database, 3)
    first = store.read_event_page(task.task_id, -1, limit=1)
    SQLiteEventStore(database).append(
        SessionEvent.create(
            session_id=task.active_segment_id,
            sequence=3,
            actor=EventActor.SYSTEM,
            event_type=EventType.SESSION_TITLE_UPDATED,
            payload={"title": "Late"},
        )
    )
    second = store.read_event_page(
        task.task_id,
        first.next_sequence,
        through_sequence=first.highwater,
    )
    assert [entry.task_sequence for entry in second.events] == [1, 2]
    assert second.highwater == 2 and not second.has_more
    fresh = store.read_event_page(task.task_id, second.next_sequence)
    assert [entry.task_sequence for entry in fresh.events] == [3]


def test_byte_budget_is_applied_before_body_decoding(tmp_path: Path, monkeypatch) -> None:
    from agent_storage import task_event_pages

    store, task = _task(tmp_path / "pages.sqlite", 6)
    original = task_event_pages.deserialize_event_row
    decoded = []

    def counted(row):
        decoded.append(row["task_sequence"])
        return original(row)

    monkeypatch.setattr(task_event_pages, "deserialize_event_row", counted)
    page = store.read_event_page(task.task_id, -1, max_bytes=1024)
    assert len(decoded) == len(page.events) == 1
    assert page.byte_count <= 1024 and page.has_more


def test_minimum_budget_can_read_a_small_event(tmp_path: Path) -> None:
    store, task = _task(tmp_path / "pages.sqlite", 1)
    page = store.read_event_page(task.task_id, -1, max_bytes=1024)
    assert len(page.events) == 1 and page.byte_count <= 1024 and not page.has_more


def test_metadata_admission_never_evaluates_candidate_payload_lengths(tmp_path: Path) -> None:
    from agent_storage.task_event_pages import read_task_event_page

    database = tmp_path / "pages.sqlite"
    store, task = _task(database, 1)
    for sequence in range(1, 7):
        SQLiteEventStore(database).append(
            SessionEvent.create(
                session_id=task.active_segment_id,
                sequence=sequence,
                actor=EventActor.SYSTEM,
                event_type=EventType.SESSION_TITLE_UPDATED,
                payload={"title": "x" * 1_048_576},
            )
        )
    touched = []
    with SQLiteDatabase(database).connect() as connection:
        connection.create_function(
            "length", 1, lambda value: touched.append(len(value)) or len(value)
        )
        page = read_task_event_page(
            connection, task.task_id, -1, limit=256, max_bytes=1024, through=None
        )
    assert len(page.events) == 1
    assert touched == []  # Source writes/backfill own size computation, not observers.


def test_oversized_event_is_explicit_and_not_hydrated(tmp_path: Path, monkeypatch) -> None:
    from agent_storage import task_event_pages

    database = tmp_path / "pages.sqlite"
    store, task = _task(database, 1)
    SQLiteEventStore(database).append(
        SessionEvent.create(
            session_id=task.active_segment_id,
            sequence=1,
            actor=EventActor.SYSTEM,
            event_type=EventType.SESSION_TITLE_UPDATED,
            payload={"title": "x" * 5000},
        )
    )
    monkeypatch.setattr(task_event_pages, "deserialize_event_row", lambda _: pytest.fail("decoded"))
    with pytest.raises(ValueError, match="byte budget"):
        store.read_event_page(task.task_id, 0, max_bytes=4096)


@pytest.mark.parametrize(
    "options",
    [
        {"limit": 0},
        {"limit": 257},
        {"limit": True},
        {"max_bytes": 0},
        {"max_bytes": 1_048_577},
        {"through_sequence": 99},
    ],
)
def test_invalid_page_budgets_and_highwater_are_rejected(tmp_path: Path, options) -> None:
    store, task = _task(tmp_path / "pages.sqlite", 1)
    with pytest.raises(ValueError):
        store.read_event_page(task.task_id, -1, **options)


def test_page_does_not_implicitly_adopt_or_repair_history(tmp_path: Path) -> None:
    database = tmp_path / "pages.sqlite"
    store, task = _task(database, 3)
    with SQLiteDatabase(database).connect() as connection:
        connection.execute("UPDATE agent_tasks SET event_position_state='assigning'")
    with pytest.raises(ValueError, match="explicit backfill"):
        store.read_event_page(task.task_id, -1)
    with SQLiteDatabase(database).connect() as connection:
        assert (
            connection.execute("SELECT event_position_state FROM agent_tasks").fetchone()[0]
            == "assigning"
        )

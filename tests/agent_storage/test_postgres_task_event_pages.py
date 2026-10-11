"""Database seek pages never hydrate the full Task history or cross namespaces."""

from pathlib import Path

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import PostgresAgentTaskStore, PostgresEventStore

from tests.agent_storage.test_postgres_agent_tasks import _seed_session
from tests.agent_storage.test_postgres_agent_tasks import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_agent_tasks import task_namespace as _namespace_fixture

postgres_dsn = _pg_fixture
task_namespace = _namespace_fixture


def _task(dsn: str, namespace: str, path: Path, count: int):
    session = _seed_session(dsn, namespace, path, "Pages")
    history = PostgresEventStore(dsn, deployment_namespace=namespace)
    for sequence in range(len(history.list_for_session(session)), count):
        history.append(
            SessionEvent.create(
                session_id=session,
                sequence=sequence,
                actor=EventActor.SYSTEM,
                event_type=EventType.SESSION_TITLE_UPDATED,
                payload={"title": "Pages"},
            )
        )
    store = PostgresAgentTaskStore(dsn, deployment_namespace=namespace)
    task = store.ensure_for_session(session)
    while not store.backfill_event_positions(task.task_id):
        pass
    return store, task


def test_postgres_page_bounds_body_decoding(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_storage.postgres import task_event_pages

    store, task = _task(postgres_dsn, task_namespace, tmp_path / "pages", 300)
    decoded = []
    original = task_event_pages.task_event_from_row

    def counted(task_id, row):
        decoded.append(row["task_sequence"])
        return original(task_id, row)

    monkeypatch.setattr(task_event_pages, "task_event_from_row", counted)
    page = store.read_event_page(task.task_id, 250, limit=3)
    assert decoded == [251, 252, 253]
    assert [entry.task_sequence for entry in page.events] == decoded
    assert page.highwater == 299 and page.has_more
    assert page.byte_count <= 1_048_576
    decoded.clear()
    assert len(store.read_event_page(task.task_id, 250, max_bytes=1024).events) == 1
    assert decoded == [251]


def test_postgres_page_freezes_highwater_but_sees_later_silent_events(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    store, task = _task(postgres_dsn, task_namespace, tmp_path / "pages", 3)
    first = store.read_event_page(task.task_id, -1, limit=1)
    PostgresEventStore(postgres_dsn, deployment_namespace=task_namespace).append(
        SessionEvent.create(
            session_id=task.active_segment_id,
            sequence=3,
            actor=EventActor.SYSTEM,
            event_type=EventType.SESSION_TITLE_UPDATED,
            payload={"title": "Late"},
        )
    )
    second = store.read_event_page(
        task.task_id, first.next_sequence, through_sequence=first.highwater
    )
    assert [entry.task_sequence for entry in second.events] == [1, 2]
    assert second.highwater == 2 and not second.has_more
    assert store.read_event_page(task.task_id, 2).events[0].task_sequence == 3
    empty = store.read_event_page(task.task_id, 3)
    assert empty.events == () and empty.highwater == 3 and not empty.has_more


def test_postgres_page_rejects_oversized_body_before_decoding(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_storage.postgres import task_event_pages

    store, task = _task(postgres_dsn, task_namespace, tmp_path / "pages", 3)
    PostgresEventStore(postgres_dsn, deployment_namespace=task_namespace).append(
        SessionEvent.create(
            session_id=task.active_segment_id,
            sequence=3,
            actor=EventActor.SYSTEM,
            event_type=EventType.SESSION_TITLE_UPDATED,
            payload={"title": "x" * 5000},
        )
    )
    monkeypatch.setattr(
        task_event_pages,
        "task_event_from_row",
        lambda *_: pytest.fail("oversized body was decoded"),
    )
    with pytest.raises(ValueError, match="byte budget"):
        store.read_event_page(task.task_id, 2, max_bytes=4096)


def test_postgres_page_does_not_mutate_backfill_state_or_read_another_namespace(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    store, task = _task(postgres_dsn, task_namespace, tmp_path / "pages", 3)
    other = PostgresAgentTaskStore(postgres_dsn, deployment_namespace="other-namespace")
    with pytest.raises(ValueError, match="not found"):
        other.read_event_page(task.task_id, -1)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE agent_tasks SET event_position_state='assigning' "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (task_namespace, task.task_id),
        )
    with pytest.raises(ValueError, match="explicit backfill"):
        store.read_event_page(task.task_id, -1)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT event_position_state FROM agent_tasks "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (task_namespace, task.task_id),
        ).fetchone() == ("assigning",)


@pytest.mark.parametrize(
    "options",
    [{"limit": 257}, {"limit": True}, {"max_bytes": 1_048_577}, {"through_sequence": 999}],
)
def test_postgres_page_rejects_invalid_bounds(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
    options,
) -> None:
    store, task = _task(postgres_dsn, task_namespace, tmp_path / "pages", 3)
    with pytest.raises(ValueError):
        store.read_event_page(task.task_id, -1, **options)

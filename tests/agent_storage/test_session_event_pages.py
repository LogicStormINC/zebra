"""Native source byte admission precedes Session body hydration on both adapters."""

from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage import PostgresEventStore, sqlite_control_plane_stores

from tests.agent_storage.test_postgres_agent_tasks import _seed_session
from tests.agent_storage.test_postgres_agent_tasks import postgres_dsn as _dsn_fixture
from tests.agent_storage.test_postgres_agent_tasks import task_namespace as _namespace_fixture

task_namespace = _namespace_fixture
postgres_dsn = _dsn_fixture


@pytest.fixture(params=["sqlite", "postgres"])
def page_store(request, tmp_path: Path):
    if request.param == "postgres":
        dsn = request.getfixturevalue("postgres_dsn")
        namespace = request.getfixturevalue("task_namespace")
        sid = _seed_session(dsn, namespace, tmp_path, "Pages")
        return PostgresEventStore(dsn, deployment_namespace=namespace), sid
    stores = sqlite_control_plane_stores(tmp_path / "pages.sqlite")
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Pages",
            user_input="你好🙂",
            workspace_root=tmp_path,
        )
    )
    for event in bootstrap.events:
        stores.events.append(event)
    return stores.events, bootstrap.session.session_id


def test_bounded_session_pages_resume_at_one_captured_highwater(page_store):
    store, sid = page_store
    highwater = store.read_session_highwater(sid)
    cursor, seen = -1, []
    while cursor < highwater:
        page = store.read_session_event_page(sid, cursor, through_sequence=highwater, limit=1)
        assert len(page.events) == 1 and 0 < page.byte_count <= 1_048_576
        seen.extend(page.events)
        cursor = page.next_sequence
    assert [event.sequence for event in seen] == list(range(highwater + 1))
    assert store.read_session_event_page(sid, cursor).events == ()
    with pytest.raises(ValueError):
        store.read_session_event_page(sid, highwater + 1)


@pytest.mark.parametrize("text", ["中" * 400_000, "🙂" * 300_000], ids=["Chinese", "emoji"])
def test_oversized_utf8_event_rejected_before_body_hydration(page_store, monkeypatch, text):
    store, sid = page_store
    after = store.read_session_highwater(sid)
    store.append(
        SessionEvent.create(
            session_id=sid,
            sequence=after + 1,
            event_type=EventType.MODEL_RESPONSE_DELTA,
            actor=EventActor.HARNESS,
            payload={
                "content_delta": text,
                "attempt_number": 1,
                "model_call_id": "call",
                "delta_index": 0,
            },
        )
    )
    # The metadata rejection must happen before a SessionEvent is constructed.
    monkeypatch.setattr(
        SessionEvent,
        "model_validate",
        lambda *args, **kwargs: (pytest.fail("oversized source body was hydrated")),
    )
    with pytest.raises(ValueError, match="byte budget"):
        store.read_session_event_page(sid, after)


def test_standalone_sqlite_bounded_read_requires_prepared_metadata(tmp_path):
    from agent_core.domain.identifiers import new_session_id
    from agent_storage import SQLiteEventStore

    store, sid = SQLiteEventStore(tmp_path / "legacy.sqlite"), new_session_id()
    store.append(
        SessionEvent.create(
            session_id=sid,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Legacy"},
        )
    )
    with pytest.raises(CheckpointNotReady):
        store.read_session_event_page(sid, -1)
    assert len(store.read_since(sid, -1)) == 1

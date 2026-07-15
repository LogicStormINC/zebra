from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.session_history import SessionHistoryMode, SessionHistoryRequest
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteSessionHistory


def test_history_browse_is_newest_first_and_excludes_current_session(tmp_path: Path) -> None:
    database = tmp_path / "history.db"
    first = _stored_session(database, "First", "alpha", minute=1)
    current = _stored_session(database, "Current", "current", minute=3)
    second = _stored_session(database, "Second", "beta", minute=2)

    result = SQLiteSessionHistory(database).query(
        SessionHistoryRequest(
            mode=SessionHistoryMode.BROWSE,
            limit=10,
            current_session_id=str(current),
        )
    )

    assert [item.session_id for item in result.sessions] == [str(second), str(first)]
    assert [item.snippet for item in result.sessions] == ["beta", "alpha"]


def test_history_search_ranks_title_then_message_and_hides_control_payloads(
    tmp_path: Path,
) -> None:
    database = tmp_path / "history.db"
    title_hit = _stored_session(database, "Needle title", "ordinary", minute=1)
    message_hit = _stored_session(database, "Other", "needle body", minute=2)
    store = SQLiteEventStore(database)
    store.append(
        SessionEvent.create(
            session_id=message_hit,
            sequence=4,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={
                "attempt_number": 1,
                "tool_name": "command.run",
                "status": "executed",
                "output": "SECRET-CONTROL-NEEDLE",
                "metadata": {},
            },
            created_at=_at(2),
        )
    )

    result = SQLiteSessionHistory(database).query(
        SessionHistoryRequest(mode=SessionHistoryMode.SEARCH, query="needle", limit=10)
    )

    assert [item.session_id for item in result.sessions] == [str(title_hit), str(message_hit)]
    assert all("SECRET-CONTROL" not in (item.snippet or "") for item in result.sessions)
    assert result.scanned_messages == 4


def test_history_read_pages_only_user_and_assistant_text(tmp_path: Path) -> None:
    database = tmp_path / "history.db"
    session_id = _stored_session(database, "Read me", "user text", minute=1)
    history = SQLiteSessionHistory(database)

    first_page = history.query(
        SessionHistoryRequest(
            mode=SessionHistoryMode.READ,
            session_id=str(session_id),
            limit=1,
        )
    )

    result = history.query(
        SessionHistoryRequest(
            mode=SessionHistoryMode.READ,
            session_id=str(session_id),
            offset=1,
            limit=1,
        )
    )
    active_session = history.query(
        SessionHistoryRequest(
            mode=SessionHistoryMode.READ,
            session_id=str(session_id),
            current_session_id=str(session_id),
        )
    )

    assert [(item.role, item.content) for item in first_page.messages] == [
        ("user", "user text")
    ]
    assert first_page.next_offset == 1
    assert first_page.truncated is True
    assert [(item.role, item.content) for item in result.messages] == [
        ("assistant", "assistant text")
    ]
    assert result.total_count == 2
    assert result.next_offset is None
    assert active_session.sessions == ()
    assert active_session.messages == ()


def _stored_session(database: Path, title: str, prompt: str, *, minute: int):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title=title,
            user_input=prompt,
            workspace_root=database.parent,
            created_at=_at(minute),
        )
    )
    store = SQLiteEventStore(database)
    for event in bootstrap.events:
        store.append(event)
    store.append(
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=3,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": "assistant text"},
            created_at=_at(minute),
        )
    )
    SQLiteProjectionStore(database).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _at(minute: int) -> datetime:
    return datetime(2026, 7, 15, tzinfo=UTC) + timedelta(minutes=minute)

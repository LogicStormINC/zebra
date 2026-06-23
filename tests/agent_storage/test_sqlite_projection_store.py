from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteProjectionStore


def test_sqlite_projection_store_saves_and_loads_session(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    created_at = datetime(2026, 6, 19, 23, 15, tzinfo=UTC)
    session = Session.create(title="Stored Session", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.RUNNING,
            "current_sequence": 3,
            "updated_at": created_at,
        }
    )

    store.save_session(session)

    loaded = store.get_session(session.session_id)

    assert loaded == session


def test_sqlite_projection_store_returns_none_for_unknown_session(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    session = Session.create(
        title="Unknown Session",
        created_at=datetime(2026, 6, 19, 23, 20, tzinfo=UTC),
    )

    assert store.get_session(session.session_id) is None


def test_sqlite_projection_store_lists_ready_sessions_in_update_order(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    base_time = datetime(2026, 6, 19, 23, 30, tzinfo=UTC)
    first = Session.create(title="first", created_at=base_time).model_copy(
        update={
            "status": SessionStatus.READY,
            "updated_at": base_time,
        }
    )
    second = Session.create(title="second", created_at=base_time).model_copy(
        update={
            "status": SessionStatus.READY,
            "updated_at": base_time.replace(minute=31),
        }
    )
    running = Session.create(title="running", created_at=base_time).model_copy(
        update={
            "status": SessionStatus.RUNNING,
            "updated_at": base_time.replace(minute=32),
        }
    )
    store.save_session(second)
    store.save_session(running)
    store.save_session(first)

    ready = store.list_ready_sessions(limit=10)

    assert [session.session_id for session in ready] == [first.session_id, second.session_id]


def test_sqlite_projection_store_respects_ready_session_limit(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    base_time = datetime(2026, 6, 19, 23, 40, tzinfo=UTC)
    first = Session.create(title="first", created_at=base_time).model_copy(
        update={"status": SessionStatus.READY, "updated_at": base_time}
    )
    second = Session.create(title="second", created_at=base_time).model_copy(
        update={
            "status": SessionStatus.READY,
            "updated_at": base_time.replace(minute=41),
        }
    )
    store.save_session(first)
    store.save_session(second)

    ready = store.list_ready_sessions(limit=1)

    assert [session.session_id for session in ready] == [first.session_id]

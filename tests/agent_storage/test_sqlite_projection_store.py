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

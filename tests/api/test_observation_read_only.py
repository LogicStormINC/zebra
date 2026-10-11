"""Legacy observations must not create Tasks or hydrate canonical history."""

import sqlite3
from pathlib import Path

import pytest
from agent_core.domain.sessions import Session, SessionStatus
from zebra_agent_api import RouteAdapter, RouteRequest, create_app


@pytest.mark.parametrize("surface", ["session", "stream", "approvals", "approval"])
def test_legacy_observation_does_not_adopt_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    database = tmp_path / "read-only.sqlite"
    app = create_app(database)
    session = Session.create(title="Legacy approval").model_copy(
        update={"status": SessionStatus.WAITING_APPROVAL}
    )
    app.stores.sessions.save_session(session)
    paths = {
        "session": f"/sessions/{session.session_id}",
        "stream": f"/sessions/{session.session_id}/stream",
        "approvals": "/approvals",
        "approval": f"/approvals/{session.session_id}",
    }

    def no_adoption(*args: object, **kwargs: object) -> None:
        raise AssertionError("an observation tried to adopt a Task")

    monkeypatch.setattr(app.stores.tasks, "ensure_for_session", no_adoption)
    response = RouteAdapter(app).handle(RouteRequest("GET", paths[surface]))

    assert response.status_code == 200
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM agent_tasks").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM execution_segments").fetchone()[0] == 0


def test_task_lookup_uses_only_existing_segment_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(tmp_path / "lookup.sqlite")
    session = Session.create(title="Unprepared")
    app.stores.sessions.save_session(session)
    lookup = app.stores.tasks.task_id_for_session
    assert lookup(session.session_id) is None
    task = app.stores.tasks.ensure_for_session(session.session_id)

    def no_history(*args: object, **kwargs: object) -> None:
        raise AssertionError("scalar identity lookup hydrated Task history")

    monkeypatch.setattr(app.stores.tasks, "get_task", no_history)
    monkeypatch.setattr(app.stores.tasks, "read_events", no_history)
    monkeypatch.setattr(app.stores.tasks, "ensure_for_session", no_history)
    assert lookup(session.session_id) == task.task_id

"""Hot observation reads must not hydrate a Task's historical event stream."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from zebra_agent_api import RouteAdapter, RouteRequest, create_app


def test_header_uses_scalar_reads_and_preserves_control_revision(tmp_path, monkeypatch) -> None:
    app = create_app(tmp_path / "header.sqlite")
    adapter = RouteAdapter(app)
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Header",
                "prompt": "Inspect",
                "workspace": str(tmp_path),
            },
        )
    )
    task_id = str(created.body["task_id"])
    previous = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))

    def forbidden(*_args, **_kwargs):
        pytest.fail("Header must not hydrate Task membership or historical bodies")

    for name in ("get_task", "segments", "read_events", "ensure_for_session"):
        monkeypatch.setattr(app.stores.tasks, name, forbidden)
    monkeypatch.setattr(app.stores.events, "list_for_session", forbidden)
    monkeypatch.setattr(app.stores.sessions, "get_session", forbidden)
    monkeypatch.setattr(app.stores.workspaces, "get_workspace", forbidden)
    read = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}/header"))
    assert read.status_code == 200
    for key in (
        "task_id",
        "session_id",
        "title",
        "status",
        "current_sequence",
        "active_segment_sequence",
    ):
        assert read.body[key] == previous.body[key]
    assert read.body["active_segment_id"] == task_id
    assert (
        not {
            "turn_id",
            "current_turn_status",
            "model_usage",
            "attachments",
            "workspace",
            "approval_context",
            "task_plan",
        }
        & read.body.keys()
    )
    assert read.body["title_truncated"] is False


@pytest.mark.parametrize("identity,status", [("invalid", 400), (str(uuid4()), 404)])
def test_header_rejects_missing_or_invalid_targets(tmp_path, identity, status) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "missing.sqlite"))
    read = adapter.handle(RouteRequest("GET", f"/tasks/{identity}/header"))
    assert read.status_code == status


def test_unprepared_header_is_not_backfilled_by_observation(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite"
    app = create_app(database)
    adapter = RouteAdapter(app)
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Legacy",
                "prompt": "Inspect",
                "workspace": str(tmp_path),
            },
        )
    )
    task_id = str(created.body["task_id"])
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE agent_tasks SET event_position_state='pending' WHERE task_id=?", (task_id,)
        )
    with pytest.raises(CheckpointNotReady):
        adapter.handle(RouteRequest("GET", f"/tasks/{task_id}/header"))
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT event_position_state FROM agent_tasks WHERE task_id=?", (task_id,)
        ).fetchone() == ("pending",)


def test_missing_session_header_is_explicit_and_get_does_not_repair(tmp_path: Path) -> None:
    path = tmp_path / "missing-header.sqlite"
    adapter = RouteAdapter(create_app(path))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Legacy",
                "prompt": "Inspect",
                "workspace": str(tmp_path),
            },
        )
    )
    task_id = str(created.body["task_id"])
    with sqlite3.connect(path) as database:
        database.execute("DELETE FROM session_observation_headers")
    read = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}/header"))
    assert read.status_code == 409 and read.body["status"] == "projection_incomplete"
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT COUNT(*) FROM session_observation_headers").fetchone() == (
            0,
        )

import base64
from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from zebra_agent_api import RouteAdapter, RouteRequest, create_app

NOW = datetime(2026, 7, 19, tzinfo=UTC)


def test_task_create_list_and_control_route_to_active_segment(tmp_path: Path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite"))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={"title": "Public task", "prompt": "Inspect", "workspace": str(tmp_path)},
        )
    )
    task_id = created.body["task_id"]
    cancelled = adapter.handle(RouteRequest("POST", f"/tasks/{task_id}/cancel", body={}))
    read = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))

    assert created.status_code == 201
    assert created.body["session_id"] == task_id
    assert cancelled.body["session_id"] == task_id
    assert cancelled.body["status"] == "cancelled"
    assert read.body["status"] == "cancelled"


def test_task_routes_keep_one_identity_across_automatic_follow_up_rollover(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.sqlite"
    task_id = str(_seed_completed(database, tmp_path))
    adapter = RouteAdapter(create_app(database))

    before = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    appended = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={
                "content": "Continue without showing an internal thread",
                "attachments": [
                    {
                        "file_name": "context.txt",
                        "media_type": "text/plain",
                        "content_base64": base64.b64encode(b"durable context").decode(),
                    }
                ],
            },
            headers={"Idempotency-Key": "follow-up-1"},
        )
    )
    replayed = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={
                "content": "Continue without showing an internal thread",
                "attachments": [
                    {
                        "file_name": "context.txt",
                        "media_type": "text/plain",
                        "content_base64": base64.b64encode(b"durable context").decode(),
                    }
                ],
            },
            headers={"Idempotency-Key": "follow-up-1"},
        )
    )
    after = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    listing = adapter.handle(RouteRequest("GET", "/tasks", query={"limit": "10"}))
    stream = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}/stream"))
    internal = adapter.handle(RouteRequest("GET", f"/internal/tasks/{task_id}/segments"))

    assert before.status_code == 200
    assert appended.status_code == 201
    assert appended.body["rolled_over"] is True
    assert appended.body["session_id"] == task_id
    assert appended.body["attachments"][0]["file_name"] == "context.txt"
    assert replayed.body == appended.body
    assert after.body["session_id"] == task_id
    assert after.body["task_id"] == task_id
    assert after.body["status"] == "ready"
    assert listing.body["count"] == 1
    assert len(internal.body["segments"]) == 2
    assert internal.body["segments"][1]["rollover_reason"] == "terminal_follow_up"
    assert "handoff_id" not in str(stream.body)
    assert (
        sum(
            event["payload"].get("content") == "Continue without showing an internal thread"
            for event in stream.body["events"]
        )
        == 1
    )


def test_internal_rollover_controller_pauses_unsafe_boundary(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite"
    task_id = str(_seed_completed(database, tmp_path))
    response = RouteAdapter(create_app(database)).handle(
        RouteRequest(
            "POST",
            f"/internal/tasks/{task_id}/segments/rollover",
            body={"signals": {"agent_rollover_hint": True, "pending_approval": True}},
        )
    )

    assert response.body == {
        "task_id": task_id,
        "decision": "pause_for_approval_or_clarification",
    }


def _seed_completed(database: Path, workspace: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Stable task",
            user_input="Start",
            workspace_root=workspace.resolve(),
            created_at=NOW,
        )
    )
    events = [
        *bootstrap.events,
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=4,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        ),
    ]
    store = SQLiteEventStore(database)
    for event in events:
        store.append(event)
    SQLiteProjectionStore(database).save_session(rebuild_session(events))
    SQLiteWorkspaceProjectionStore(database).save_workspace(rebuild_workspace(events))
    return bootstrap.session.session_id

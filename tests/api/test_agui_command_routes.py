from __future__ import annotations

from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    sqlite_control_plane_stores,
)
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_run_command_validates_agui_input_and_appends_only_intent(tmp_path: Path) -> None:
    database_path, thread_id, revision = _seed_ready_session(tmp_path)
    adapter = _adapter(database_path)
    request = RouteRequest(
        method="POST",
        path="/agui/commands",
        headers={"Idempotency-Key": "agui-run-1"},
        body={
            "action": "run",
            "threadId": str(thread_id),
            "runId": "segment-1",
            "expectedRevision": revision,
            "input": _run_input(thread_id, "segment-1"),
        },
    )

    response = adapter.handle(request)

    assert response.status_code == 202
    assert response.body["status"] == "accepted"
    assert response.body["threadId"] == str(thread_id)
    assert response.body["runId"] == "segment-1"
    events = SQLiteEventStore(database_path).list_for_session(thread_id)
    assert len(events) == revision + 2
    assert events[-1].event_type is EventType.SESSION_COMMAND_ACCEPTED
    assert events[-1].payload["kind"] == "run"
    assert events[-1].payload["payload"]["run_id"] == "segment-1"


def test_resume_and_stop_use_durable_commands(tmp_path: Path) -> None:
    database_path, thread_id, revision = _seed_ready_session(tmp_path)
    adapter = _adapter(database_path)
    resume = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/agui/threads/{thread_id}/runs/resume-1/commands",
            headers={"Idempotency-Key": "agui-resume-1"},
            body={
                "action": "resume",
                "expectedRevision": revision,
                "input": {
                    **_run_input(thread_id, "resume-1"),
                    "resume": [
                        {"interruptId": "approval:tool-1", "status": "resolved", "payload": {}}
                    ],
                },
            },
        )
    )
    stop = adapter.handle(
        RouteRequest(
            method="POST",
            path="/agui/commands",
            headers={"Idempotency-Key": "agui-stop-1"},
            body={
                "action": "stop",
                "threadId": str(thread_id),
                "runId": "segment-2",
                "expectedRevision": revision + 1,
            },
        )
    )

    assert resume.status_code == 202
    assert stop.status_code == 202
    events = SQLiteEventStore(database_path).list_for_session(thread_id)
    assert [event.payload["kind"] for event in events[-2:]] == ["resume", "stop"]


def test_duplicate_and_stale_commands_are_problem_details(tmp_path: Path) -> None:
    database_path, thread_id, revision = _seed_ready_session(tmp_path)
    adapter = _adapter(database_path)
    request = RouteRequest(
        method="POST",
        path="/agui/commands",
        headers={"Idempotency-Key": "agui-duplicate-1"},
        body={
            "action": "stop",
            "threadId": str(thread_id),
            "runId": "segment-3",
            "expectedRevision": revision,
        },
    )

    first = adapter.handle(request)
    duplicate = adapter.handle(request)
    stale_body = dict(request.body or {})
    stale_body["expectedRevision"] = revision
    stale = adapter.handle(
        RouteRequest(
            method="POST",
            path="/agui/commands",
            headers={"Idempotency-Key": "agui-stale-1"},
            body=stale_body,
        )
    )

    assert first.status_code == 202
    assert duplicate.status_code == 200
    assert duplicate.body["status"] == "duplicate"
    assert stale.status_code == 409
    assert str(stale.body["type"]).endswith("/revision_conflict")
    assert stale.body["status"] == 409


def test_invalid_agui_command_fails_before_command_service(tmp_path: Path) -> None:
    database_path, thread_id, revision = _seed_ready_session(tmp_path)
    adapter = _adapter(database_path)

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path="/agui/commands",
            headers={"Idempotency-Key": "agui-invalid-1"},
            body={
                "action": "run",
                "threadId": str(thread_id),
                "runId": "segment-4",
                "expectedRevision": revision,
                "input": {"messages": [{"role": "unknown"}]},
            },
        )
    )
    missing_key = adapter.handle(
        RouteRequest(
            method="POST",
            path="/agui/commands",
            body={
                "action": "stop",
                "threadId": str(thread_id),
                "runId": "segment-4",
                "expectedRevision": revision,
            },
        )
    )

    assert response.status_code == 400
    assert str(response.body["type"]).endswith("/invalid_request")
    assert missing_key.status_code == 400
    assert str(missing_key.body["type"]).endswith("/missing_idempotency_key")
    assert len(SQLiteEventStore(database_path).list_for_session(thread_id)) == revision + 1


def test_agui_command_module_has_no_worker_execution_import() -> None:
    source = Path("apps/api/src/zebra_agent_api/ag_ui_command.py").read_text()

    assert "SessionExecutionService" not in source
    assert "run_local_harness" not in source
    assert "SessionClaimService" not in source


def _adapter(database_path: Path) -> RouteAdapter:
    stores = sqlite_control_plane_stores(database_path)
    return RouteAdapter(create_app(database_path, stores=stores))


def _run_input(thread_id: object, run_id: str) -> dict[str, object]:
    return {
        "threadId": str(thread_id),
        "runId": run_id,
        "state": {},
        "messages": [],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


def _seed_ready_session(tmp_path: Path) -> tuple[Path, SessionId, int]:
    database_path = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="AG-UI command",
            user_input="Queue the command.",
            workspace_root=tmp_path.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        rebuild_workspace(list(bootstrap.events))
    )
    return database_path, bootstrap.session.session_id, bootstrap.session.current_sequence

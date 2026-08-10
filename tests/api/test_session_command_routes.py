from __future__ import annotations

from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventType
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    sqlite_control_plane_stores,
)
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import load_settings


def test_command_route_appends_intent_without_runtime_side_effect(tmp_path: Path) -> None:
    database_path, session_id, expected_revision = _seed_ready_session(tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/commands",
            headers={"Idempotency-Key": "run-1"},
            body={"kind": "run", "expected_revision": expected_revision},
        )
    )

    assert response.status_code == 202
    assert response.body["status"] == "accepted"
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert events[-1].event_type is EventType.SESSION_COMMAND_ACCEPTED
    assert SQLiteProjectionStore(database_path).get_session(session_id).current_sequence == (
        expected_revision
    )


def test_duplicate_command_replays_without_revision_conflict(tmp_path: Path) -> None:
    database_path, session_id, expected_revision = _seed_ready_session(tmp_path)
    adapter = RouteAdapter(create_app(database_path))
    request = RouteRequest(
        method="POST",
        path=f"/sessions/{session_id}/commands",
        headers={"Idempotency-Key": "run-duplicate"},
        body={"kind": "run", "expected_revision": expected_revision},
    )

    first = adapter.handle(request)
    second = adapter.handle(request)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.body["status"] == "duplicate"
    assert second.body["event_sequence"] == first.body["event_sequence"]
    assert len(SQLiteEventStore(database_path).list_for_session(session_id)) == (
        expected_revision + 2
    )


def test_revision_conflict_does_not_append_command(tmp_path: Path) -> None:
    database_path, session_id, expected_revision = _seed_ready_session(tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/commands",
            headers={"Idempotency-Key": "run-stale"},
            body={"kind": "run", "expected_revision": expected_revision - 1},
        )
    )

    assert response.status_code == 409
    assert response.body["status"] == "revision_conflict"
    assert len(SQLiteEventStore(database_path).list_for_session(session_id)) == (
        expected_revision + 1
    )


def test_command_route_requires_header_and_valid_payload(tmp_path: Path) -> None:
    database_path, session_id, expected_revision = _seed_ready_session(tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    missing_key = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/commands",
            body={"kind": "message", "expected_revision": expected_revision},
        )
    )
    invalid_message = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/commands",
            headers={"Idempotency-Key": "message-1"},
            body={"kind": "message", "expected_revision": expected_revision},
        )
    )

    assert missing_key.status_code == 400
    assert invalid_message.status_code == 400


def test_cloud_message_route_submits_command_instead_of_executing_inline(tmp_path: Path) -> None:
    database_path, session_id, expected_revision = _seed_ready_session(tmp_path)
    settings = load_settings(
        {
            "ZEBRA_PROFILE": "cloud",
            "ZEBRA_DATABASE_URL": "postgresql://zebra:test@db/zebra",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        }
    )
    adapter = RouteAdapter(
        create_app(
            database_path,
            settings=settings,
            stores=sqlite_control_plane_stores(database_path),
        )
    )

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/messages",
            headers={"Idempotency-Key": "cloud-message-1"},
            body={"content": "continue", "expected_revision": expected_revision},
        )
    )

    assert response.status_code == 202
    assert response.body["kind"] == "message"
    assert response.body["status"] == "accepted"


def _seed_ready_session(tmp_path: Path):
    database_path = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Command route",
            user_input="Run the durable command.",
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

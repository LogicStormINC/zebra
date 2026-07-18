import json
from pathlib import Path

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from fastapi.testclient import TestClient
from http_app_support import (
    _created_at,
)
from zebra_agent_api import create_http_app


def test_http_app_serves_health(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "zebra-agent-api",
        "status": "ok",
        "runtime": {
            "profile": "local",
            "runtime_class": "trusted-local",
            "fallback_allowed": False,
        },
    }

def test_http_app_serves_session_lookup(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="HTTP session")
    )
    client = TestClient(create_http_app(database_path))

    response = client.get(f"/sessions/{session.session_id}")

    assert response.status_code == 200
    assert response.json()["session_id"] == str(session.session_id)
    assert response.json()["title"] == "HTTP session"

def test_http_app_session_lookup_rejects_invalid_session_id(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.get("/sessions/not-a-valid-uuid")

    assert response.status_code == 400
    assert response.json() == {
        "session_id": "not-a-valid-uuid",
        "status": "invalid_request",
        "reason": "session_id must be a valid UUID",
    }

def test_http_app_serves_proxy_approval_context_on_session_lookup(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = Session.create(title="Waiting approval").model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "current_sequence": 3,
            "approval_context": ApprovalContext(
                tool_name="mcp.github.create_pull_request",
                reason="proxy-routed external tool execution in test",
                policy_profile="full_access",
                route="mcp_proxy",
                target="github.create_pull_request",
                network_profile="mcp-proxy-only",
                scope=(
                    "tool:mcp.github.create_pull_request",
                    "route:mcp_proxy",
                    "network_profile:mcp-proxy-only",
                    "target:github.create_pull_request",
                ),
            ),
        }
    )
    SQLiteProjectionStore(database_path).save_session(session)
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.APPROVAL_REQUESTED,
            actor=EventActor.POLICY,
            payload={
                "attempt_number": 1,
                "tool_name": "mcp.github.create_pull_request",
                "reason": "proxy-routed external tool execution in test",
                "policy_profile": "full_access",
                "route": "mcp_proxy",
                "target": "github.create_pull_request",
                "network_profile": "mcp-proxy-only",
                "scope": [
                    "tool:mcp.github.create_pull_request",
                    "route:mcp_proxy",
                    "network_profile:mcp-proxy-only",
                    "target:github.create_pull_request",
                ],
            },
            created_at=_created_at(),
        )
    )
    client = TestClient(create_http_app(database_path))

    response = client.get(f"/sessions/{session.session_id}")

    assert response.status_code == 200
    assert response.json()["approval_context"] == {
        "tool_name": "mcp.github.create_pull_request",
        "reason": "proxy-routed external tool execution in test",
        "policy_profile": "full_access",
        "route": "mcp_proxy",
        "target": "github.create_pull_request",
        "network_profile": "mcp-proxy-only",
        "scope": [
            "tool:mcp.github.create_pull_request",
            "route:mcp_proxy",
            "network_profile:mcp-proxy-only",
            "target:github.create_pull_request",
        ],
    }

def test_http_app_serves_workspace_projection_on_session_lookup(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = Session.create(title="Workspace HTTP").model_copy(
        update={
            "status": SessionStatus.SUSPENDED,
            "current_sequence": 4,
        }
    )
    SQLiteProjectionStore(database_path).save_session(session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        WorkspaceProjection.model_validate(
            {
                "session_id": session.session_id,
                "workspace_root": str(tmp_path.resolve()),
                "prepared_at": _created_at(),
                "updated_at": _created_at(),
                "current_sequence": 4,
                "status": WorkspaceStatus.SUSPENDED,
                "policy_profile": "workspace_write",
                "last_attempt_number": 1,
                "runtime_name": "local",
                "snapshot_id": "snap-http-1",
                "snapshot_path": "/tmp/zebra-agent-runtime/snap-http-1",
            }
        )
    )
    client = TestClient(create_http_app(database_path))

    response = client.get(f"/sessions/{session.session_id}")

    assert response.status_code == 200
    assert response.json()["workspace"] == {
        "workspace_root": str(tmp_path.resolve()),
        "tool_profile": "coding",
        "network_profile": "none",
        "network_allowlist": [],
        "status": "suspended",
        "current_sequence": 4,
        "prepared_at": _created_at().isoformat(),
        "updated_at": _created_at().isoformat(),
        "policy_profile": "workspace_write",
        "last_attempt_number": 1,
        "runtime_name": "local",
        "snapshot": {
            "runtime_name": "local",
            "snapshot_id": "snap-http-1",
            "snapshot_path": "/tmp/zebra-agent-runtime/snap-http-1",
        },
    }

def test_http_app_returns_not_found_for_unknown_path(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {
        "method": "GET",
        "path": "/missing",
        "status": "not_found",
    }

def test_http_app_returns_not_found_for_unsupported_method(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post("/health")

    assert response.status_code == 404
    assert response.json() == {
        "method": "POST",
        "path": "/health",
        "status": "not_found",
    }

def test_http_app_streams_session_events_as_sse(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="HTTP stream")
    )
    event_store = SQLiteEventStore(database_path)
    event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": session.title},
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": session.title,
                "user_input": "stream me",
            },
        )
    )
    client = TestClient(create_http_app(database_path))

    response = client.get(f"/sessions/{session.session_id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = [chunk for chunk in response.text.strip().split("\n\n") if chunk]
    assert len(chunks) == 2
    assert "id: 0" in chunks[0]
    assert "id: 1" in chunks[1]
    assert "event: session_event" in chunks[0]
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    data_lines = [line for line in chunks[0].splitlines() if line.startswith("data: ")]
    first_event = json.loads(data_lines[0].removeprefix("data: "))
    assert first_event["sequence"] == 0
    assert first_event["event_type"] == EventType.SESSION_CREATED.value

def test_http_app_stream_rejects_invalid_after_sequence(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="HTTP stream cursor")
    )
    client = TestClient(create_http_app(database_path))

    response = client.get(
        f"/sessions/{session.session_id}/stream?after_sequence=invalid"
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "invalid_request",
        "reason": "after_sequence must be an integer greater than or equal to -1",
    }

def test_http_app_stream_missing_session_returns_not_found(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.get("/sessions/00000000-0000-0000-0000-000000000001/stream")

    assert response.status_code == 404
    assert response.json() == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }

def test_http_app_stream_rejects_invalid_session_id(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.get("/sessions/not-a-valid-uuid/stream")

    assert response.status_code == 400
    assert response.json() == {
        "session_id": "not-a-valid-uuid",
        "status": "invalid_request",
        "reason": "session_id must be a valid UUID",
    }

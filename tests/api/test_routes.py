from datetime import UTC, datetime
from pathlib import Path

import zebra_agent_worker.execution as worker_execution_module
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_route_adapter_handles_health(tmp_path: Path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "sessions.sqlite"))

    response = adapter.handle(RouteRequest(method="GET", path="/health"))

    assert response.status_code == 200
    assert response.body["status"] == "ok"


def test_route_adapter_handles_session_lookup(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Route session")
    )
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(method="GET", path=f"/sessions/{session.session_id}")
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert response.body["title"] == "Route session"


def test_route_adapter_handles_approval_list(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_approval_session(database_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(RouteRequest(method="GET", path="/approvals"))

    assert response.status_code == 200
    assert response.body["approvals"][0]["approval_id"] == str(session.session_id)


def test_route_adapter_handles_approval_detail(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_approval_session(database_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(method="GET", path=f"/approvals/{session.session_id}")
    )

    assert response.status_code == 200
    assert response.body["approval_id"] == str(session.session_id)


def test_route_adapter_returns_not_found_for_unknown_route(tmp_path: Path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "sessions.sqlite"))

    response = adapter.handle(RouteRequest(method="POST", path="/health"))

    assert response.status_code == 404
    assert response.body == {
        "method": "POST",
        "path": "/health",
        "status": "not_found",
    }


def test_route_adapter_handles_session_create(tmp_path: Path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "sessions.sqlite"))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path="/sessions",
            body={
                "prompt": "Create one session",
                "title": "Route create session",
            },
        )
    )

    assert response.status_code == 201
    assert response.body["executed"] is False
    assert response.body["title"] == "Route create session"


def test_route_adapter_handles_session_stream(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Route stream")
    )
    event = SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": session.title},
        )
    )
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(method="GET", path=f"/sessions/{session.session_id}/stream")
    )
    events = response.body["events"]

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert isinstance(events, list)
    assert events[0]["event_id"] == str(event.event_id)


def test_route_adapter_handles_session_resume_execute(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(worker_execution_module, "build_model_gateway", _fake_model_gateway)
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/resume",
            body={"worker_id": "route-worker", "lease_ttl_seconds": 45},
        )
    )

    assert response.status_code == 200
    assert response.body["session_id"] == session_id
    assert response.body["executed"] is True
    assert response.body["worker_id"] == "route-worker"
    assert response.body["status"] == "completed"
    assert response.body["assistant_message"] == "Route execution complete."
    assert response.body["trace"] == [
        {
            "attempt_number": 1,
            "assistant_message": "Route execution complete.",
            "tools": [],
        }
    ]


def test_route_adapter_handles_session_suspend(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/suspend",
            body={},
        )
    )

    assert response.status_code == 200
    assert response.body["session_id"] == session_id
    assert response.body["suspended"] is True
    assert response.body["status"] == "suspended"


def test_route_adapter_handles_session_message_append(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/messages",
            body={"content": "Please continue from the latest checkpoint."},
        )
    )

    assert response.status_code == 201
    assert response.body["session_id"] == session_id
    assert response.body["appended"] is True
    assert response.body["content"] == "Please continue from the latest checkpoint."
    assert response.body["status"] == "ready"
    assert response.body["current_sequence"] == 3


def test_route_adapter_rejects_terminal_session_message_append(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Terminal route").model_copy(
            update={"status": SessionStatus.COMPLETED}
        )
    )
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session.session_id}/messages",
            body={"content": "Try again."},
        )
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "not_appendable",
        "reason": "cannot_append_to_terminal_session",
    }


def test_route_adapter_rejects_invalid_resume_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/resume",
            body={"lease_ttl_seconds": 0},
        )
    )

    assert response.status_code == 400
    assert response.body == {
        "status": "invalid_request",
        "reason": "lease_ttl_seconds must be greater than zero",
    }


def test_route_adapter_rejects_invalid_suspend_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/suspend",
            body={"unexpected": True},
        )
    )

    assert response.status_code == 400
    assert response.body == {
        "status": "invalid_request",
        "reason": "suspend does not accept request fields yet",
    }


def test_route_adapter_rejects_invalid_message_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/messages",
            body={"content": "   "},
        )
    )

    assert response.status_code == 400
    assert response.body == {
        "status": "invalid_request",
        "reason": "content must be a non-blank string",
    }


def test_route_adapter_returns_not_found_for_invalid_session_subpath(tmp_path: Path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "sessions.sqlite"))

    response = adapter.handle(
        RouteRequest(
            method="GET",
            path="/sessions/00000000-0000-0000-0000-000000000001/unknown",
        )
    )

    assert response.status_code == 404
    assert response.body == {
        "method": "GET",
        "path": "/sessions/00000000-0000-0000-0000-000000000001/unknown",
        "status": "not_found",
    }


def _seed_ready_session(database_path: Path, *, workspace_root: Path) -> str:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Route queued session",
            user_input="Summarize the workspace",
            workspace_root=workspace_root,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return str(bootstrap.session.session_id)


def _fake_model_gateway(_settings):
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Route execution complete.",
                        created_at=datetime(2026, 6, 22, 13, 25, tzinfo=UTC),
                    )
                )
            ),
        )
    )


def _seed_waiting_approval_session(database_path: Path) -> Session:
    session = Session.create(title="Waiting approval").model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "current_sequence": 2,
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
                ),
            ),
        }
    )
    return SQLiteProjectionStore(database_path).save_session(session)

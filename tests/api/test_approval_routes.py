from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import ApprovalContext, Session
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_route_adapter_handles_approval_grant(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{session.session_id}/approve",
            body={"operator": "alice", "reason": "safe"},
        )
    )

    assert response.status_code == 200
    assert response.body["approval_id"] == str(session.session_id)
    assert response.body["decision"] == "approve"
    assert response.body["status"] == "running"


def test_route_adapter_handles_approval_reject(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{session.session_id}/reject",
            body={},
        )
    )

    assert response.status_code == 200
    assert response.body["approval_id"] == str(session.session_id)
    assert response.body["decision"] == "reject"
    assert response.body["status"] == "failed"


def test_route_adapter_rejects_invalid_approval_state(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No approval needed")
    )
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{session.session_id}/approve",
            body={},
        )
    )

    assert response.status_code == 409
    assert response.body["status"] == "invalid_state"


def test_route_adapter_rejects_invalid_approval_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{session.session_id}/reject",
            body={"operator": "   "},
        )
    )

    assert response.status_code == 400
    assert response.body == {
        "status": "invalid_request",
        "reason": "operator must be a non-blank string when provided",
    }


def _seed_waiting_session(
    database_path: Path,
    *,
    title: str = "Waiting approval",
    approval_context: ApprovalContext | None = None,
) -> Session:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title=title,
            user_input="Approval fixture",
            workspace_root=database_path.parent,
        )
    )
    events = list(bootstrap.events)
    for event_type in (EventType.HARNESS_ATTEMPT_STARTED, EventType.APPROVAL_REQUESTED):
        events.append(
            SessionEvent.create(
                session_id=bootstrap.session.session_id,
                sequence=len(events),
                event_type=event_type,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": 1,
                    **(
                        approval_context.to_mapping()
                        if event_type is EventType.APPROVAL_REQUESTED and approval_context
                        else {}
                    ),
                },
            )
        )
    for event in events:
        SQLiteEventStore(database_path).append(event)
    session = SQLiteProjectionStore(database_path).save_session(rebuild_session(events))
    SQLiteAgentTaskStore(database_path).ensure_for_session(session.session_id)
    return session

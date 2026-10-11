from pathlib import Path

from agent_core.domain.events import EventType
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api.app import create_app

from tests.api.test_approval_routes import _seed_waiting_session


def test_api_approve_records_granted_decision(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    original_events = SQLiteEventStore(database_path).list_for_session(session.session_id)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        WorkspaceProjection(
            session_id=session.session_id,
            workspace_root=str(tmp_path),
            prepared_at=session.created_at,
            updated_at=session.updated_at,
            current_sequence=session.current_sequence,
            status=WorkspaceStatus.WAITING_APPROVAL,
        )
    )

    response = create_app(database_path).approve(
        str(session.session_id),
        {"operator": "alice", "reason": "safe to continue"},
    )

    events = SQLiteEventStore(database_path).list_for_session(session.session_id)
    updated = SQLiteProjectionStore(database_path).get_session(session.session_id)
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session.session_id)

    assert response.status_code == 200
    assert response.body == {
        "approval_id": str(session.session_id),
        "session_id": str(session.session_id),
        "decision": "approve",
        "event_type": EventType.APPROVAL_GRANTED.value,
        "sequence": session.current_sequence + 1,
        "status": SessionStatus.RUNNING.value,
    }
    assert events[: len(original_events)] == original_events
    assert [event.sequence for event in events] == list(range(len(events)))
    assert len(events) == len(original_events) + 2
    assert events[-2].event_type is EventType.APPROVAL_GRANTED
    assert events[-1].event_type is EventType.SESSION_COMMAND_ACCEPTED
    assert events[-1].idempotency_key == (
        f"approval:{session.session_id}:{session.current_sequence + 1}:resume"
    )
    assert updated is not None
    assert updated.status is SessionStatus.RUNNING
    assert workspace is not None
    assert workspace.status is WorkspaceStatus.RUNNING
    assert workspace.current_sequence == updated.current_sequence == session.current_sequence + 1


def test_api_reject_records_rejected_decision(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)

    response = create_app(database_path).reject(str(session.session_id), {})

    events = SQLiteEventStore(database_path).list_for_session(session.session_id)
    updated = SQLiteProjectionStore(database_path).get_session(session.session_id)

    assert response.status_code == 200
    assert response.body["decision"] == "reject"
    assert response.body["event_type"] == EventType.APPROVAL_REJECTED.value
    assert [event.sequence for event in events] == list(range(len(events)))
    assert events[-1].event_type is EventType.APPROVAL_REJECTED
    assert events[-1].sequence == session.current_sequence + 1
    assert events[-1].payload == {
        "operator": "api-operator",
        "reason": "reject via API",
    }
    assert updated is not None
    assert updated.status is SessionStatus.FAILED


def test_api_approval_includes_proxy_approval_context_when_present(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session_with_proxy_approval(database_path)

    response = create_app(database_path).approve(
        str(session.session_id),
        {"operator": "alice", "reason": "safe to continue"},
    )

    assert response.status_code == 200
    assert response.body["approval_context"] == {
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


def test_api_approval_returns_invalid_state_for_non_waiting_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No approval needed")
    )

    response = create_app(database_path).approve(str(session.session_id), {})

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "invalid_state",
        "reason": "approval decisions require a waiting approval session",
    }


def test_api_approval_returns_not_found_for_missing_session(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").reject(
        "00000000-0000-0000-0000-000000000001",
        {},
    )

    assert response.status_code == 404
    assert response.body == {
        "approval_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def _seed_waiting_session_with_proxy_approval(database_path: Path) -> Session:
    return _seed_waiting_session(
        database_path,
        approval_context=ApprovalContext(
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
    )

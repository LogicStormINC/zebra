from pathlib import Path

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_cli.cli import execute


def test_approval_decision_contract_matrix_grant_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    api_database_path = tmp_path / "api-grant.sqlite"
    api_session = _seed_waiting_session_with_proxy_approval(api_database_path)
    cli_database_path = tmp_path / "cli-grant.sqlite"
    cli_session = _seed_waiting_session_with_proxy_approval(
        cli_database_path,
        session=api_session,
    )

    api_response = create_app(api_database_path).approve(
        str(api_session.session_id),
        {"operator": "alice", "reason": "safe to continue"},
    )
    cli_result = execute(
        [
            "approve",
            str(cli_session.session_id),
            "--decision",
            "approve",
            "--operator",
            "alice",
            "--reason",
            "safe to continue",
            "--database",
            str(cli_database_path),
        ]
    )

    assert api_response.status_code == 200
    assert _normalize_api_approval_decision(
        api_response.body
    ) == _normalize_cli_approval_decision(cli_result.payload)


def test_approval_decision_contract_matrix_reject_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    api_database_path = tmp_path / "api-reject.sqlite"
    api_session = _seed_waiting_session_with_proxy_approval(api_database_path)
    cli_database_path = tmp_path / "cli-reject.sqlite"
    cli_session = _seed_waiting_session_with_proxy_approval(
        cli_database_path,
        session=api_session,
    )

    api_response = create_app(api_database_path).reject(str(api_session.session_id), {})
    cli_result = execute(
        [
            "approve",
            str(cli_session.session_id),
            "--decision",
            "reject",
            "--database",
            str(cli_database_path),
        ]
    )

    assert api_response.status_code == 200
    assert _normalize_api_approval_decision(
        api_response.body
    ) == _normalize_cli_approval_decision(cli_result.payload)


def test_approval_decision_contract_matrix_invalid_state_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invalid.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No approval needed")
    )

    api_response = create_app(database_path).approve(str(session.session_id), {})
    cli_result = execute(
        [
            "approve",
            str(session.session_id),
            "--decision",
            "approve",
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 409
    assert _normalize_api_approval_decision(
        api_response.body
    ) == _normalize_cli_approval_decision(cli_result.payload)


def test_approval_decision_contract_matrix_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "missing.sqlite"
    approval_id = "00000000-0000-0000-0000-000000000001"

    api_response = create_app(database_path).reject(approval_id, {})
    cli_result = execute(
        [
            "approve",
            approval_id,
            "--decision",
            "reject",
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 404
    assert _normalize_api_approval_decision(
        api_response.body
    ) == _normalize_cli_approval_decision(cli_result.payload)


def _normalize_api_approval_decision(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _normalize_cli_approval_decision(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "database"
    }


def _seed_waiting_session_with_proxy_approval(
    database_path: Path,
    *,
    session: Session | None = None,
) -> Session:
    seeded_session = session or Session.create(title="Waiting approval").model_copy(
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
                    "network_profile:mcp-proxy-only",
                    "target:github.create_pull_request",
                ),
            ),
        }
    )
    stored = SQLiteProjectionStore(database_path).save_session(seeded_session)
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=stored.session_id,
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
        )
    )
    return stored

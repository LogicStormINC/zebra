from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_storage import SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_cli.cli import execute


def test_approval_queue_contract_matrix_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    first = _waiting_session("First approval").model_copy(update={"current_sequence": 3})
    second = _waiting_session("Second approval").model_copy(
        update={
            "current_sequence": 4,
            "updated_at": _created_at().replace(second=21),
        }
    )
    SQLiteProjectionStore(database_path).save_session(first)
    SQLiteProjectionStore(database_path).save_session(second)

    api_response = create_app(database_path).list_approvals()
    cli_result = execute(["approval", "queue", "--database", str(database_path)])

    assert api_response.status_code == 200
    assert _normalize_api_approval_queue(api_response.body) == _normalize_cli_approval_queue(
        cli_result.payload
    )


def test_approval_queue_contract_matrix_empty_list_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"

    api_response = create_app(database_path).list_approvals()
    cli_result = execute(["approval", "queue", "--database", str(database_path)])

    assert api_response.status_code == 200
    assert _normalize_api_approval_queue(api_response.body) == _normalize_cli_approval_queue(
        cli_result.payload
    )


def test_approval_detail_contract_matrix_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _waiting_session("Approval detail").model_copy(update={"current_sequence": 5})
    SQLiteProjectionStore(database_path).save_session(session)

    api_response = create_app(database_path).get_approval(str(session.session_id))
    cli_result = execute(
        [
            "approval",
            "inspect",
            str(session.session_id),
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 200
    assert _normalize_api_approval_detail(api_response.body) == _normalize_cli_approval_detail(
        cli_result.payload
    )


def test_approval_detail_contract_matrix_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    approval_id = "00000000-0000-0000-0000-000000000001"

    api_response = create_app(database_path).get_approval(approval_id)
    cli_result = execute(
        [
            "approval",
            "inspect",
            approval_id,
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 404
    assert _normalize_api_approval_detail(api_response.body) == _normalize_cli_approval_detail(
        cli_result.payload
    )


def _normalize_api_approval_queue(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _normalize_cli_approval_queue(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "database"
    }


def _normalize_api_approval_detail(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _normalize_cli_approval_detail(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "database"
    }


def _waiting_session(title: str) -> Session:
    return Session.create(title=title).model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "approval_context": ApprovalContext(
                tool_name="mcp.call",
                reason="needs permission",
                policy_profile="workspace_write",
                route="mcp_proxy",
                target="github",
                scope=("pull_request:write",),
            ),
            "created_at": _created_at(),
            "updated_at": _created_at(),
        }
    )


def _created_at() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)

from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_storage import SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_approval_queue_lists_waiting_sessions(tmp_path: Path) -> None:
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

    result = execute(["approval", "queue", "--database", str(database_path)])

    assert result.command == "approval"
    assert result.payload["database"] == str(database_path)
    approvals = result.payload["approvals"]
    assert isinstance(approvals, list)
    assert approvals[0]["approval_id"] == str(first.session_id)
    assert approvals[1]["approval_id"] == str(second.session_id)
    assert approvals[0]["approval_context"]["route"] == "mcp_proxy"


def test_cli_approval_inspect_reads_waiting_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _waiting_session("Approval detail").model_copy(update={"current_sequence": 5})
    SQLiteProjectionStore(database_path).save_session(session)

    result = execute(
        [
            "approval",
            "inspect",
            str(session.session_id),
            "--database",
            str(database_path),
        ]
    )

    assert result.command == "approval"
    assert result.payload["database"] == str(database_path)
    assert result.payload["status"] == SessionStatus.WAITING_APPROVAL.value
    assert result.payload["approval_id"] == str(session.session_id)
    assert result.payload["title"] == "Approval detail"
    assert result.payload["approval_context"]["route"] == "mcp_proxy"


def test_cli_approval_inspect_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "approval",
            "inspect",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "approval_id": "00000000-0000-0000-0000-000000000001",
        "database": str(database_path),
        "status": "not_found",
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

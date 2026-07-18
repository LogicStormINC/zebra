from pathlib import Path

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from cli_run_support import (
    _created_at,
)
from zebra_agent_cli.cli import execute


def test_cli_inspect_command_reads_local_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Inspect me")
    )

    result = execute(["inspect", str(session.session_id), "--database", str(database_path)])

    assert result.command == "inspect"
    assert result.payload["session_id"] == str(session.session_id)
    assert result.payload["title"] == "Inspect me"

def test_cli_inspect_command_includes_workspace_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Inspect workspace").model_copy(
            update={
                "status": SessionStatus.SUSPENDED,
                "current_sequence": 4,
            }
        )
    )
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        WorkspaceProjection.model_validate(
            {
                "session_id": session.session_id,
                "workspace_root": str(tmp_path.resolve()),
                "prepared_at": _created_at(),
                "updated_at": _created_at(),
                "current_sequence": 4,
                "status": WorkspaceStatus.SUSPENDED,
                "runtime_name": "local",
                "snapshot_id": "snap-cli-2",
                "snapshot_path": "/tmp/zebra-agent-runtime/snap-cli-2",
            }
        )
    )

    result = execute(["inspect", str(session.session_id), "--database", str(database_path)])

    assert result.payload["workspace"] == {
        "workspace_root": str(tmp_path.resolve()),
        "tool_profile": "coding",
        "network_profile": "none",
        "network_allowlist": [],
        "status": "suspended",
        "current_sequence": 4,
        "prepared_at": _created_at().isoformat(),
        "updated_at": _created_at().isoformat(),
        "runtime_name": "local",
        "snapshot": {
            "runtime_name": "local",
            "snapshot_id": "snap-cli-2",
            "snapshot_path": "/tmp/zebra-agent-runtime/snap-cli-2",
        },
    }

def test_cli_inspect_command_includes_approval_context(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Inspect approval context").model_copy(
            update={
                "status": SessionStatus.WAITING_APPROVAL,
                "approval_context": ApprovalContext(
                    tool_name="mcp.github.create_pr",
                    reason="Approval required before opening a pull request.",
                    policy_profile="workspace_write",
                    route="mcp_proxy",
                    target="github",
                    network_profile="domain-allowlist",
                    scope=("pull_requests:write",),
                ),
            }
        )
    )

    result = execute(["inspect", str(session.session_id), "--database", str(database_path)])

    assert result.payload["approval_context"] == {
        "tool_name": "mcp.github.create_pr",
        "reason": "Approval required before opening a pull request.",
        "policy_profile": "workspace_write",
        "route": "mcp_proxy",
        "target": "github",
        "network_profile": "domain-allowlist",
        "scope": ["pull_requests:write"],
    }

def test_cli_inspect_command_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "inspect",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "database": str(database_path),
        "status": "not_found",
    }

def test_cli_approve_command_records_granted_decision(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    waiting = Session.create(title="Needs approval").model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "current_sequence": 2,
        }
    )
    SQLiteProjectionStore(database_path).save_session(waiting)

    result = execute(
        [
            "approve",
            str(waiting.session_id),
            "--decision",
            "approve",
            "--reason",
            "safe",
            "--database",
            str(database_path),
        ]
    )
    events = SQLiteEventStore(database_path).list_for_session(waiting.session_id)
    session = SQLiteProjectionStore(database_path).get_session(waiting.session_id)

    assert result.payload["session_id"] == str(waiting.session_id)
    assert result.payload["decision"] == "approve"
    assert result.payload["event_type"] == EventType.APPROVAL_GRANTED.value
    assert result.payload["sequence"] == 3
    assert result.payload["status"] == SessionStatus.RUNNING.value
    assert events[0].event_type is EventType.APPROVAL_GRANTED
    assert session is not None
    assert session.status is SessionStatus.RUNNING

def test_cli_approve_command_rejects_non_waiting_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No approval needed")
    )

    result = execute(
        [
            "approve",
            str(session.session_id),
            "--decision",
            "reject",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload["status"] == "invalid_state"
    assert "waiting approval" in str(result.payload["reason"])

def test_cli_approve_requires_valid_decision() -> None:
    with pytest.raises(SystemExit):
        execute(
            [
                "approve",
                "00000000-0000-0000-0000-000000000001",
                "--decision",
                "maybe",
            ]
        )

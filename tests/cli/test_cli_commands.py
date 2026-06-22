import json
from pathlib import Path
from uuid import UUID

import pytest
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import SessionStatus
from agent_storage import SQLiteProjectionStore
from zebra_agent_cli.cli import execute, main


def test_cli_run_command_creates_local_session(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "sessions.sqlite"

    assert (
        main(
            [
                "run",
                "Fix tests",
                "--title",
                "Fix failing tests",
                "--database",
                str(database_path),
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    session_id = SessionId(UUID(output["session_id"]))
    session = SQLiteProjectionStore(database_path).get_session(session_id)

    assert output["command"] == "run"
    assert output["prompt"] == "Fix tests"
    assert output["status"] == SessionStatus.CREATED.value
    assert output["title"] == "Fix failing tests"
    assert output["workspace"] == "."
    assert output["database"] == str(database_path)
    assert session is not None
    assert session.title == "Fix failing tests"
    assert session.status is SessionStatus.CREATED


def test_cli_resume_command_outputs_session_intent() -> None:
    result = execute(["resume", "session-1"])

    assert result.payload == {
        "session_id": "session-1",
        "status": "accepted",
    }


def test_cli_inspect_command_outputs_session_intent() -> None:
    result = execute(["inspect", "session-1"])

    assert result.command == "inspect"
    assert result.payload["session_id"] == "session-1"


def test_cli_approve_command_outputs_decision_intent() -> None:
    result = execute(
        ["approve", "approval-1", "--decision", "reject", "--reason", "unsafe"]
    )

    assert result.payload == {
        "approval_id": "approval-1",
        "decision": "reject",
        "reason": "unsafe",
        "status": "accepted",
    }


def test_cli_approve_requires_valid_decision() -> None:
    with pytest.raises(SystemExit):
        execute(["approve", "approval-1", "--decision", "maybe"])

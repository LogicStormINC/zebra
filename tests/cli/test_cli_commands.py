import json

import pytest
from zebra_agent_cli.cli import execute, main


def test_cli_run_command_outputs_task_intent(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "Fix tests", "--title", "Fix failing tests"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "command": "run",
        "prompt": "Fix tests",
        "status": "created",
        "title": "Fix failing tests",
        "workspace": ".",
    }


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

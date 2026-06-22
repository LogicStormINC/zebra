import json
from pathlib import Path
from uuid import UUID

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute, main
from zebra_agent_config import ModelSettings, ZebraAgentSettings


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
    events = SQLiteEventStore(database_path).list_for_session(session_id)

    assert output["command"] == "run"
    assert output["prompt"] == "Fix tests"
    assert output["status"] == SessionStatus.CREATED.value
    assert output["title"] == "Fix failing tests"
    assert output["workspace"] == "."
    assert output["database"] == str(database_path)
    assert session is not None
    assert session.title == "Fix failing tests"
    assert session.status is SessionStatus.CREATED
    assert len(events) == 1
    assert events[0].event_type is EventType.SESSION_CREATED
    assert events[0].payload == {"title": "Fix failing tests"}


def test_cli_run_command_uses_settings_database_by_default(tmp_path: Path) -> None:
    database_path = tmp_path / "configured.sqlite"

    result = execute(
        ["run", "Use configured database"],
        settings=_settings(database_path),
    )
    session = SQLiteProjectionStore(database_path).get_session(
        SessionId(UUID(str(result.payload["session_id"])))
    )
    events = SQLiteEventStore(database_path).list_for_session(
        SessionId(UUID(str(result.payload["session_id"])))
    )

    assert result.payload["database"] == str(database_path)
    assert session is not None
    assert len(events) == 1


def test_cli_run_command_database_option_overrides_settings(tmp_path: Path) -> None:
    configured_path = tmp_path / "configured.sqlite"
    explicit_path = tmp_path / "explicit.sqlite"

    result = execute(
        [
            "run",
            "Use explicit database",
            "--database",
            str(explicit_path),
        ],
        settings=_settings(configured_path),
    )

    assert result.payload["database"] == str(explicit_path)
    assert SQLiteProjectionStore(explicit_path).get_session(
        SessionId(UUID(str(result.payload["session_id"])))
    ) is not None
    assert not configured_path.exists()


def test_cli_resume_command_reads_local_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Resume me")
    )

    result = execute(["resume", str(session.session_id), "--database", str(database_path)])

    assert result.command == "resume"
    assert result.payload["session_id"] == str(session.session_id)
    assert result.payload["database"] == str(database_path)
    assert result.payload["title"] == "Resume me"
    assert result.payload["status"] == SessionStatus.CREATED.value
    assert result.payload["current_sequence"] == 0


def test_cli_inspect_command_reads_local_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Inspect me")
    )

    result = execute(["inspect", str(session.session_id), "--database", str(database_path)])

    assert result.command == "inspect"
    assert result.payload["session_id"] == str(session.session_id)
    assert result.payload["title"] == "Inspect me"


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


def _settings(database_path: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )

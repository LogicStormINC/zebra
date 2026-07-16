import json
import sys
from pathlib import Path
from uuid import UUID

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import SessionStatus
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from cli_run_support import (
    _settings,
)
from zebra_agent_cli.cli import execute, main
from zebra_agent_config import McpServerSettings


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
    assert output["executed"] is False
    assert output["status"] == SessionStatus.READY.value
    assert output["title"] == "Fix failing tests"
    assert output["tool_profile"] == "general"
    assert output["workspace"] == "."
    assert output["database"] == str(database_path)
    assert session is not None
    assert session.title == "Fix failing tests"
    assert session.status is SessionStatus.READY
    assert len(events) == 3
    assert events[0].event_type is EventType.SESSION_CREATED
    assert events[0].payload == {"title": "Fix failing tests"}
    assert events[1].event_type is EventType.USER_MESSAGE_RECEIVED
    assert events[1].payload == {"content": "Fix tests"}
    assert events[2].event_type is EventType.TASK_PREPARED
    assert events[2].payload["workspace_root"] == str(Path(".").resolve())
    assert events[2].payload["tool_profile"] == "general"

def test_cli_run_command_persists_explicit_coding_profile(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "run",
            "Use coding tools",
            "--tool-profile",
            "coding",
            "--database",
            str(database_path),
        ]
    )
    session_id = SessionId(UUID(str(result.payload["session_id"])))
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)

    assert result.payload["tool_profile"] == "coding"
    assert workspace is not None
    assert workspace.tool_profile.value == "coding"

def test_cli_run_command_persists_network_allowlist(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "run",
            "Read allowed docs",
            "--network-profile",
            "domain-allowlist",
            "--network-allowlist",
            "Docs.Example.com",
            "--database",
            str(database_path),
        ]
    )
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(
        SessionId(UUID(str(result.payload["session_id"])))
    )

    assert result.payload["network_profile"] == "domain-allowlist"
    assert result.payload["network_allowlist"] == ["docs.example.com"]
    assert workspace is not None
    assert workspace.network_allowlist == ("docs.example.com",)

def test_cli_run_command_persists_explicit_empty_mcp_allowlist(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(["run", "Stay local", "--database", str(database_path)])
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(
        SessionId(UUID(str(result.payload["session_id"])))
    )

    assert result.payload["mcp_allowlist"] == []
    assert workspace is not None
    assert workspace.mcp_allowlist == ()

def test_cli_run_command_persists_selected_mcp_allowlist(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    script = Path(__file__).parents[2] / "fixtures" / "mcp_stdio_server.py"
    settings = _settings(
        database_path,
        mcp_servers=(
            McpServerSettings(
                name="fixture",
                command=sys.executable,
                args=(str(script), "normal"),
            ),
        ),
    )

    result = execute(
        [
            "run",
            "Use selected MCP",
            "--network-profile",
            "mcp-proxy-only",
            "--mcp-tool",
            "mcp.fixture.echo",
        ],
        settings=settings,
    )
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(
        SessionId(UUID(str(result.payload["session_id"])))
    )

    assert result.payload["mcp_allowlist"] == ["mcp.fixture.echo"]
    assert workspace is not None
    assert workspace.mcp_allowlist == ("mcp.fixture.echo",)

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
    assert len(events) == 3

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

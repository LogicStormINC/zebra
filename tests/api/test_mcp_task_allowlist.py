from __future__ import annotations

import sys
from pathlib import Path

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteWorkspaceProjectionStore
from zebra_agent_api import create_app
from zebra_agent_config import ApiSettings, McpServerSettings, ModelSettings, ZebraAgentSettings


def test_new_api_task_defaults_to_no_mcp_without_discovery(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    response = create_app(
        database,
        settings=_settings(database, mode="invalid-json"),
    ).create_session({"prompt": "Stay local"})

    assert response.status_code == 201
    assert response.body["mcp_allowlist"] == []
    workspace = SQLiteWorkspaceProjectionStore(database).get_workspace(
        SessionId(response.body["session_id"])
    )
    assert workspace is not None
    assert workspace.mcp_allowlist == ()


def test_api_persists_selected_available_mcp_tool(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    response = create_app(database, settings=_settings(database)).create_session(
        {
            "prompt": "Use selected MCP",
            "network_profile": "mcp-proxy-only",
            "mcp_allowlist": ["mcp.fixture.echo"],
        }
    )

    assert response.status_code == 201
    assert response.body["mcp_allowlist"] == ["mcp.fixture.echo"]
    session_id = SessionId(response.body["session_id"])
    prepared = SQLiteEventStore(database).list_for_session(session_id)[2]
    assert prepared.payload["mcp_allowlist"] == ["mcp.fixture.echo"]
    detail = create_app(database).get_session(str(session_id))
    assert detail.body["workspace"]["mcp_allowlist"] == ["mcp.fixture.echo"]


def test_api_rejects_invalid_or_unavailable_mcp_authority(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    app = create_app(database, settings=_settings(database))

    incompatible = app.create_session(
        {"prompt": "No route", "mcp_allowlist": ["mcp.fixture.echo"]}
    )
    duplicate = app.create_session(
        {
            "prompt": "Duplicate",
            "network_profile": "mcp-proxy-only",
            "mcp_allowlist": ["mcp.fixture.echo", "mcp.fixture.echo"],
        }
    )
    unavailable = app.create_session(
        {
            "prompt": "Removed",
            "network_profile": "mcp-proxy-only",
            "mcp_allowlist": ["mcp.fixture.removed"],
        }
    )
    unknown_field = app.create_session(
        {"prompt": "Strict authority", "mcp_tools": ["mcp.fixture.echo"]}
    )

    assert incompatible.status_code == 400
    assert "MCP-capable" in str(incompatible.body["reason"])
    assert duplicate.status_code == 400
    assert "unique" in str(duplicate.body["reason"])
    assert unavailable.status_code == 400
    assert "unavailable" in str(unavailable.body["reason"])
    assert unknown_field.status_code == 400
    assert unknown_field.body["reason"] == "unknown create-session fields: mcp_tools"


def _settings(database: Path, *, mode: str = "normal") -> ZebraAgentSettings:
    script = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        mcp_servers=(
            McpServerSettings(
                name="fixture",
                command=sys.executable,
                args=(str(script), mode),
            ),
        ),
    )

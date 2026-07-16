from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from zebra_agent_api import create_app, create_http_app
from zebra_agent_config import (
    ApiSettings,
    McpServerSettings,
    ModelSettings,
    ZebraAgentSettings,
)


def test_api_returns_explicit_unconfigured_inventory(tmp_path: Path) -> None:
    response = create_app(
        tmp_path / "sessions.sqlite",
        settings=_settings(tmp_path),
    ).get_mcp_capabilities()

    assert response.status_code == 200
    assert response.body["status"] == "unconfigured"
    assert response.body["servers"] == []


def test_api_returns_safe_configured_inventory(tmp_path: Path) -> None:
    response = create_app(
        tmp_path / "sessions.sqlite",
        settings=_settings(tmp_path, mcp_servers=(_server(),)),
    ).get_mcp_capabilities()

    assert response.status_code == 200
    assert response.body["status"] == "available"
    assert response.body["tool_count"] == 1
    assert response.body["servers"][0]["tools"][0]["input_fields"] == ["value"]
    assert "command" not in repr(response.body)


def test_api_returns_unavailable_without_stale_tools(tmp_path: Path) -> None:
    response = create_app(
        tmp_path / "sessions.sqlite",
        settings=_settings(tmp_path, mcp_servers=(_server("invalid-json"),)),
    ).get_mcp_capabilities()

    assert response.status_code == 503
    assert response.body["status"] == "unavailable"
    assert response.body["configured"] is True
    assert response.body["servers"] == []
    assert response.body["tool_count"] == 0
    assert response.body["resource_count"] == 0


def test_http_mcp_inventory_requires_configured_auth_token(tmp_path: Path) -> None:
    client = TestClient(
        create_http_app(
            tmp_path / "sessions.sqlite",
            settings=_settings(tmp_path, auth_token="secret"),
        )
    )

    assert client.get("/health").status_code == 200
    assert client.get("/capabilities/mcp").status_code == 401
    response = client.get(
        "/capabilities/mcp",
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unconfigured"


def _server(mode: str = "normal") -> McpServerSettings:
    script = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    return McpServerSettings(
        name="fixture",
        command=sys.executable,
        args=(str(script), mode),
    )


def _settings(
    tmp_path: Path,
    *,
    auth_token: str | None = None,
    mcp_servers: tuple[McpServerSettings, ...] = (),
) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(tmp_path / "sessions.sqlite"),
        api=ApiSettings(auth_token=auth_token),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        mcp_servers=mcp_servers,
    )

from __future__ import annotations

import json

import pytest
from zebra_agent_config.mcp_settings import (
    MAX_MCP_SERVERS,
    McpHttpServerSettings,
    _read_mcp_servers,
)


def _values(payload: object) -> dict[str, str]:
    return {"ZEBRA_MCP_SERVERS": json.dumps(payload)}


def test_read_mcp_http_server_settings() -> None:
    servers = _read_mcp_servers(
        _values(
            {
                "remote": {
                    "kind": "http",
                    "url": "https://example.test/mcp",
                    "bearer_token_env": "MCP_REMOTE_TOKEN",
                }
            }
        )
    )
    assert servers == (
        McpHttpServerSettings(
            name="remote",
            url="https://example.test/mcp",
            bearer_token_env="MCP_REMOTE_TOKEN",
        ),
    )


def test_read_mcp_http_server_requires_https_url() -> None:
    with pytest.raises(ValueError, match="https"):
        _read_mcp_servers(_values({"remote": {"kind": "http", "url": "http://example.test/mcp"}}))


def test_read_mcp_http_server_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="only url and bearer_token_env"):
        _read_mcp_servers(
            _values(
                {"remote": {"kind": "http", "url": "https://example.test/mcp", "token": "x"}}
            )
        )


def test_read_mcp_http_server_rejects_invalid_bearer_env() -> None:
    with pytest.raises(ValueError, match="bearer_token_env"):
        _read_mcp_servers(
            _values(
                {
                    "remote": {
                        "kind": "http",
                        "url": "https://example.test/mcp",
                        "bearer_token_env": "bad-name",
                    }
                }
            )
        )


def test_read_mcp_servers_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unsupported kind"):
        _read_mcp_servers(_values({"remote": {"kind": "grpc", "url": "x"}}))


def test_read_mcp_servers_shares_max_between_kinds() -> None:
    too_many = {
        f"srv{i}": {"kind": "http", "url": f"https://example{i}.test/mcp"}
        for i in range(MAX_MCP_SERVERS + 1)
    }
    with pytest.raises(ValueError, match="at most"):
        _read_mcp_servers(_values(too_many))

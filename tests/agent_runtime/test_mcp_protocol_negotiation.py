from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from agent_runtime.mcp_protocol import (
    MCP_PROTOCOL_VERSION_LATEST,
    SUPPORTED_PROTOCOL_VERSIONS,
    McpProtocolError,
    StdioMcpSession,
)


@dataclass(frozen=True)
class _Server:
    name: str
    command: str
    args: tuple[str, ...]


def _server(mode: str) -> _Server:
    script = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    return _Server(name="fixture", command=sys.executable, args=(str(script), mode))


def test_client_advertises_the_latest_supported_version() -> None:
    assert MCP_PROTOCOL_VERSION_LATEST in SUPPORTED_PROTOCOL_VERSIONS
    assert "2025-06-18" in SUPPORTED_PROTOCOL_VERSIONS


@pytest.mark.parametrize(
    "mode,expected",
    [("normal", "2025-06-18"), ("new-protocol-version", "2025-11-25")],
)
def test_session_accepts_supported_server_version(mode: str, expected: str) -> None:
    with StdioMcpSession(_server(mode), timeout_seconds=5.0) as session:
        assert session.protocol_version == expected


@pytest.mark.parametrize("mode", ["bad-protocol-version", "missing-protocol-version"])
def test_session_fails_closed_on_unsupported_server_version(mode: str) -> None:
    with pytest.raises(McpProtocolError, match="unsupported protocol version"):
        with StdioMcpSession(_server(mode), timeout_seconds=5.0):
            pass

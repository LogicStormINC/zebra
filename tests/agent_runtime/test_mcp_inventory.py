from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import agent_runtime.mcp_inventory as inventory_module
from agent_runtime import build_mcp_capability_inventory


@dataclass(frozen=True)
class _Server:
    name: str
    command: str
    args: tuple[str, ...]


def test_unconfigured_inventory_does_not_start_transport(monkeypatch) -> None:
    def fail_if_started(_servers):
        raise AssertionError("transport must not start")

    monkeypatch.setattr(inventory_module, "LocalStdioMcpTransport", fail_if_started)

    assert build_mcp_capability_inventory(()).to_mapping() == {
        "status": "unconfigured",
        "configured": False,
        "available": False,
        "server_count": 0,
        "tool_count": 0,
        "resource_count": 0,
        "servers": [],
    }


def test_inventory_projects_only_safe_deterministic_capabilities() -> None:
    inventory = build_mcp_capability_inventory((_server(),)).to_mapping()

    assert inventory == {
        "status": "available",
        "configured": True,
        "available": True,
        "server_count": 1,
        "tool_count": 1,
        "resource_count": 0,
        "servers": [
            {
                "name": "fixture",
                "tool_count": 1,
                "resource_count": 0,
                "resources": [],
                "tools": [
                    {
                        "name": "echo",
                        "description": "Untrusted external MCP capability. Echo one value.",
                        "input_fields": ["value"],
                    }
                ],
            }
        ],
    }
    serialized = repr(inventory)
    assert sys.executable not in serialized
    assert "mcp_stdio_server.py" not in serialized
    assert "inputSchema" not in serialized


def _server(mode: str = "normal") -> _Server:
    script = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    return _Server(
        name="fixture",
        command=sys.executable,
        args=(str(script), mode),
    )

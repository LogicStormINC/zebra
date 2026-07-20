from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import (
    LocalStdioMcpTransport,
    LocalToolGateway,
    McpProtocolError,
    run_local_harness,
)
from agent_security import parse_network_profile
from agent_tools import McpProxyRequest, parse_mcp_tool_name
from agent_tools.mcp_disclosure import (
    MCP_TOOL_CALL_NAME,
    MCP_TOOL_DESCRIBE_NAME,
    MCP_TOOL_SEARCH_NAME,
)


@dataclass(frozen=True)
class _Server:
    name: str
    command: str
    args: tuple[str, ...]


def test_stdio_bridge_discovers_and_executes_untrusted_tool(tmp_path: Path) -> None:
    marker = tmp_path / "called"
    transport = LocalStdioMcpTransport((_server("normal", marker),))

    assert [tool.name for tool in transport.model_tools] == ["mcp.fixture.echo"]
    assert transport.model_tools[0].parameters["required"] == ["value"]
    assert not marker.exists()

    response = transport.execute(
        McpProxyRequest(
            tool_call_id="call-1",
            target=parse_mcp_tool_name("mcp.fixture.echo"),
            arguments={"value": "zebra"},
        )
    )

    assert response.output == "UNTRUSTED MCP OUTPUT (fixture.echo)\necho:zebra"
    assert response.metadata["untrusted_output"] is True
    assert marker.read_text(encoding="utf-8") == "called"


def test_local_gateway_advertises_mcp_only_when_configured(tmp_path: Path) -> None:
    plain = LocalToolGateway(tmp_path / "plain")
    configured = LocalToolGateway(
        tmp_path / "configured",
        tool_profile=ToolProfile.GENERAL,
        mcp_servers=(_server(),),
    )

    assert not any(tool.name.startswith("mcp.") for tool in plain.model_tools)
    assert "mcp.fixture.echo" in {tool.name for tool in configured.model_tools}
    result = configured.execute(_tool_call("mcp.fixture.echo", {"value": "ok"}))
    assert result.status is ToolCallStatus.EXECUTED
    assert result.metadata["proxy_transport"] == "mcp_proxy"


def test_task_allowlist_filters_model_catalog_and_execution(tmp_path: Path) -> None:
    gateway = LocalToolGateway(
        tmp_path / "selected",
        tool_profile=ToolProfile.GENERAL,
        mcp_servers=(_server("two-tools"),),
        mcp_allowlist=("mcp.fixture.echo1",),
    )

    assert "mcp.fixture.echo1" in {tool.name for tool in gateway.model_tools}
    assert "mcp.fixture.echo" not in {tool.name for tool in gateway.model_tools}
    denied = gateway.execute(_tool_call("mcp.fixture.echo", {"value": "blocked"}))
    assert denied.status is ToolCallStatus.FAILED
    assert denied.metadata["reason"] == "mcp_proxy_error"


def test_large_mcp_catalog_uses_progressive_disclosure_bridge(tmp_path: Path) -> None:
    marker = tmp_path / "large-called"
    gateway = LocalToolGateway(
        tmp_path / "large-catalog",
        tool_profile=ToolProfile.GENERAL,
        mcp_servers=(_server("large-catalog", marker),),
    )

    tool_names = {tool.name for tool in gateway.model_tools}
    assert MCP_TOOL_SEARCH_NAME in tool_names
    assert MCP_TOOL_DESCRIBE_NAME in tool_names
    assert MCP_TOOL_CALL_NAME in tool_names
    assert "mcp.fixture.echo" not in tool_names
    assert len(gateway.effective_mcp_tools) == 16

    search = gateway.execute(_tool_call(MCP_TOOL_SEARCH_NAME, {"query": "echo", "limit": 1}))
    resolved = gateway.resolve_model_tool_calls(
        (
            _tool_call(
                MCP_TOOL_CALL_NAME,
                {"name": "mcp.fixture.echo", "arguments": {"value": "bridged"}},
            ),
        )
    )[0]
    result = gateway.execute(resolved)

    assert search.status is ToolCallStatus.EXECUTED
    assert search.output.startswith("[UNTRUSTED MCP CAPABILITY METADATA]\n")
    assert resolved.name == "mcp.fixture.echo"
    assert resolved.provider_tool_name == MCP_TOOL_CALL_NAME
    assert result.status is ToolCallStatus.EXECUTED
    assert result.output.endswith("echo:bridged")
    assert marker.read_text(encoding="utf-8") == "called"


def test_empty_task_allowlist_does_not_start_mcp_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agent_runtime.mcp_routing.LocalStdioMcpTransport",
        lambda *_args, **_kwargs: pytest.fail("MCP discovery must not start"),
    )

    gateway = LocalToolGateway(
        tmp_path / "empty",
        mcp_servers=(_server("invalid-json"),),
        mcp_allowlist=(),
    )

    assert not any(tool.name.startswith("mcp.") for tool in gateway.model_tools)


def test_task_allowlist_rejects_removed_capability(tmp_path: Path) -> None:
    with pytest.raises(McpProtocolError, match="unavailable"):
        LocalToolGateway(
            tmp_path / "removed",
            mcp_servers=(_server(),),
            mcp_allowlist=("mcp.fixture.removed",),
        )
    with pytest.raises(ValueError, match="unavailable"):
        LocalToolGateway(
            tmp_path / "all-servers-removed",
            mcp_allowlist=("mcp.fixture.echo",),
        )


def test_stdio_bridge_rejects_malformed_tool_schema() -> None:
    with pytest.raises(McpProtocolError, match="object schema"):
        LocalStdioMcpTransport((_server("malformed-schema"),))


@pytest.mark.parametrize(
    "mode, message",
    [
        ("invalid-json", "invalid JSON"),
        ("too-many-tools", "more than 16 tools"),
    ],
)
def test_stdio_bridge_fails_closed_on_invalid_discovery(mode: str, message: str) -> None:
    with pytest.raises(McpProtocolError, match=message):
        LocalStdioMcpTransport((_server(mode),))


def test_stdio_bridge_does_not_inherit_model_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-reach-mcp")
    transport = LocalStdioMcpTransport((_server("env"),))

    response = transport.execute(
        McpProxyRequest(
            tool_call_id="call-env",
            target=parse_mcp_tool_name("mcp.fixture.echo"),
            arguments={"value": "ignored"},
        )
    )

    assert response.output.endswith("echo:secret-absent")


def test_stdio_bridge_rejects_oversized_output() -> None:
    transport = LocalStdioMcpTransport((_server("oversized-output"),))

    with pytest.raises(McpProtocolError, match="output exceeds"):
        transport.execute(
            McpProxyRequest(
                tool_call_id="call-large",
                target=parse_mcp_tool_name("mcp.fixture.echo"),
                arguments={"value": "ignored"},
            )
        )


def test_stdio_bridge_rejects_unknown_target_without_starting_call() -> None:
    transport = LocalStdioMcpTransport((_server(),))

    with pytest.raises(McpProtocolError, match="discovery catalog"):
        transport.execute(
            McpProxyRequest(
                tool_call_id="call-2",
                target=parse_mcp_tool_name("mcp.fixture.missing"),
            )
        )


def test_harness_requires_approval_before_mcp_tool_call(tmp_path: Path) -> None:
    marker = tmp_path / "called"
    tool_call = _tool_call("mcp.fixture.echo", {"value": "approved-only"})
    result = run_local_harness(
        prompt="Use the configured external echo tool.",
        title="MCP approval boundary",
        workspace_root=tmp_path / "workspace",
        model_gateway=ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Calling configured MCP tool.",
                            created_at=datetime(2026, 7, 15, tzinfo=UTC),
                        ),
                        tool_calls=(tool_call,),
                    )
                ),
            )
        ),
        network_profile=parse_network_profile("mcp-proxy-only"),
        mcp_servers=(_server("normal", marker),),
    )

    assert result.session.status is SessionStatus.WAITING_APPROVAL
    assert not marker.exists()
    approval = next(
        event for event in result.events if event.event_type is EventType.APPROVAL_REQUESTED
    )
    assert approval.payload["route"] == "mcp_proxy"
    assert approval.payload["target"] == "fixture.echo"
    assert approval.payload["arguments"] == {"value": "approved-only"}


def _server(mode: str = "normal", marker: Path | None = None) -> _Server:
    script = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    args = [str(script), mode]
    if marker is not None:
        args.append(str(marker))
    return _Server(name="fixture", command=sys.executable, args=tuple(args))


def _tool_call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

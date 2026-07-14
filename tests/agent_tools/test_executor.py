from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError, ToolRegistryError, UnknownToolError
from agent_tools.executor import ToolExecutor
from agent_tools.mcp_gateway import McpProxyToolGateway
from agent_tools.mcp_proxy import McpProxyRequest, McpProxyResponse
from agent_tools.registry import ToolRegistry


def _tool_call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
    )


def test_tool_executor_runs_registered_tool() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolContract(name="command.run", required_arguments=("command",)),
        lambda call: ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="ok",
        ),
    )
    executor = ToolExecutor(registry)

    result = executor.execute(_tool_call("command.run", {"command": ["echo", "ok"]}))

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output == "ok"


def test_tool_executor_rejects_unknown_tool() -> None:
    executor = ToolExecutor(ToolRegistry())

    with pytest.raises(UnknownToolError, match="unknown tool"):
        executor.execute(_tool_call("missing.tool", {}))


def test_tool_executor_rejects_missing_required_arguments() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolContract(name="files.read", required_arguments=("path",)),
        lambda call: ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="unused",
        ),
    )
    executor = ToolExecutor(registry)

    with pytest.raises(ToolArgumentError, match="missing required arguments"):
        executor.execute(_tool_call("files.read", {}))


def test_tool_registry_rejects_duplicate_tool_registration() -> None:
    registry = ToolRegistry()
    contract = ToolContract(name="files.read")

    def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="ok",
        )

    registry.register(contract, handler)

    with pytest.raises(ToolRegistryError, match="already registered"):
        registry.register(contract, handler)


def test_tool_registry_exposes_only_explicit_parallel_safe_tools() -> None:
    registry = ToolRegistry()

    def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
        )

    registry.register(ToolContract(name="files.read", parallel_safe=True), handler)
    registry.register(ToolContract(name="command.run"), handler)

    assert registry.parallel_safe_names() == frozenset({"files.read"})


def test_tool_executor_routes_mcp_tool_through_proxy_gateway() -> None:
    proxy_transport = _FakeMcpProxyTransport()
    executor = ToolExecutor(
        ToolRegistry(),
        mcp_proxy_gateway=McpProxyToolGateway(transport=proxy_transport),
    )

    result = executor.execute(
        _tool_call(
            "mcp.github.create_pull_request",
            {"title": "Add feature"},
        )
    )

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output == "proxy-ok"
    assert result.metadata["route"] == "proxy"
    assert result.metadata["proxy_target"] == "github.create_pull_request"
    assert result.metadata["proxy_transport"] == "mcp_proxy"
    assert result.metadata["server_name"] == "github"
    assert proxy_transport.last_request is not None
    assert proxy_transport.last_request.target.tool_name == "create_pull_request"


def test_tool_executor_still_rejects_unknown_non_mcp_tool() -> None:
    executor = ToolExecutor(
        ToolRegistry(),
        mcp_proxy_gateway=McpProxyToolGateway(transport=_FakeMcpProxyTransport()),
    )

    with pytest.raises(UnknownToolError, match="unknown tool"):
        executor.execute(_tool_call("external.tool", {}))


class _FakeMcpProxyTransport:
    def __init__(self) -> None:
        self.last_request: McpProxyRequest | None = None

    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        self.last_request = request
        return McpProxyResponse(output="proxy-ok", metadata={"transport": "fake-proxy"})

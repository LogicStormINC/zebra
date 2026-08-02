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


def test_tool_executor_decodes_compound_json_and_preserves_tool_call_identity() -> None:
    received: list[ToolCall] = []
    registry = ToolRegistry()
    registry.register(
        ToolContract(
            name="proposal.submit",
            required_arguments=("accounts",),
            argument_properties={
                "accounts": {"type": "array", "items": {"type": "object"}},
            },
        ),
        lambda call: (
            received.append(call)
            or ToolResult(
                tool_call_id=call.tool_call_id,
                status=ToolCallStatus.EXECUTED,
            )
        ),
    )
    executor = ToolExecutor(registry)
    original = _tool_call("proposal.submit", {"accounts": '[{"account_ref":"main"}]'})

    result = executor.execute(original)

    assert result.status is ToolCallStatus.EXECUTED
    assert len(received) == 1
    normalized = received[0]
    assert normalized.arguments == {"accounts": [{"account_ref": "main"}]}
    assert normalized.tool_call_id == original.tool_call_id
    assert normalized.name == original.name
    assert normalized.created_at == original.created_at
    assert original.arguments == {"accounts": '[{"account_ref":"main"}]'}


def test_tool_executor_decodes_declared_object_json() -> None:
    received: list[ToolCall] = []
    registry = ToolRegistry()
    registry.register(
        ToolContract(
            name="object.submit",
            required_arguments=("payload",),
            argument_properties={
                "payload": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                }
            },
        ),
        lambda call: (
            received.append(call)
            or ToolResult(
                tool_call_id=call.tool_call_id,
                status=ToolCallStatus.EXECUTED,
            )
        ),
    )

    result = ToolExecutor(registry).execute(
        _tool_call("object.submit", {"payload": '{"name":"main"}'})
    )

    assert result.status is ToolCallStatus.EXECUTED
    assert received[0].arguments == {"payload": {"name": "main"}}


def test_tool_executor_does_not_coerce_declared_scalar_strings() -> None:
    received: list[ToolCall] = []
    registry = ToolRegistry()
    registry.register(
        ToolContract(
            name="scalar.submit",
            required_arguments=("label", "count"),
            argument_properties={
                "label": {"type": "string"},
                "count": {"type": "integer"},
            },
        ),
        lambda call: (
            received.append(call)
            or ToolResult(
                tool_call_id=call.tool_call_id,
                status=ToolCallStatus.EXECUTED,
            )
        ),
    )
    executor = ToolExecutor(registry)

    result = executor.execute(
        _tool_call("scalar.submit", {"label": '["literal"]', "count": 1})
    )
    assert result.status is ToolCallStatus.EXECUTED
    assert received[0].arguments["label"] == '["literal"]'

    with pytest.raises(ToolArgumentError, match="arguments.count.*integer") as error:
        executor.execute(_tool_call("scalar.submit", {"label": "literal", "count": "1"}))
    assert '"1"' not in str(error.value)


def test_tool_executor_rejects_wrong_nested_item_type_without_echoing_value() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolContract(
            name="proposal.submit",
            required_arguments=("evidence_coverage",),
            argument_properties={
                "evidence_coverage": {
                    "type": "array",
                    "items": {"type": "object"},
                }
            },
        ),
        lambda call: ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
        ),
    )

    with pytest.raises(ToolArgumentError) as error:
        ToolExecutor(registry).execute(
            _tool_call(
                "proposal.submit",
                {"evidence_coverage": ["sensitive-evidence-text"]},
            )
        )

    assert "arguments.evidence_coverage[0]" in str(error.value)
    assert "sensitive-evidence-text" not in str(error.value)


def test_tool_executor_accepts_correct_nested_object_array() -> None:
    received: list[ToolCall] = []
    registry = ToolRegistry()
    registry.register(
        ToolContract(
            name="proposal.submit",
            required_arguments=("evidence_coverage",),
            argument_properties={
                "evidence_coverage": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"evidence_ref": {"type": "string"}},
                        "required": ["evidence_ref"],
                        "additionalProperties": False,
                    },
                }
            },
        ),
        lambda call: (
            received.append(call)
            or ToolResult(
                tool_call_id=call.tool_call_id,
                status=ToolCallStatus.EXECUTED,
            )
        ),
    )

    result = ToolExecutor(registry).execute(
        _tool_call("proposal.submit", {"evidence_coverage": [{"evidence_ref": "e-1"}]})
    )

    assert result.status is ToolCallStatus.EXECUTED
    assert received[0].arguments == {"evidence_coverage": [{"evidence_ref": "e-1"}]}


@pytest.mark.parametrize(
    ("accounts", "expected_type"),
    [
        ("not-json", "array"),
        ('{"account_ref":"main"}', "array"),
    ],
)
def test_tool_executor_rejects_invalid_or_mismatched_compound_json(
    accounts: str,
    expected_type: str,
) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolContract(
            name="proposal.submit",
            required_arguments=("accounts",),
            argument_properties={"accounts": {"type": "array"}},
        ),
        lambda call: ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
        ),
    )

    with pytest.raises(ToolArgumentError) as error:
        ToolExecutor(registry).execute(_tool_call("proposal.submit", {"accounts": accounts}))

    assert "arguments.accounts" in str(error.value)
    assert expected_type in str(error.value)
    assert accounts not in str(error.value)


@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        ({"items": [{}]}, "missing required property"),
        ({"items": [{"name": "ok", "secret": "do-not-echo"}]}, "additionalProperties=false"),
    ],
)
def test_tool_executor_validates_nested_required_and_additional_properties(
    payload: dict[str, object],
    expected_detail: str,
) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolContract(
            name="nested.submit",
            required_arguments=("payload",),
            argument_properties={
                "payload": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                                "required": ["name"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["items"],
                    "additionalProperties": False,
                }
            },
        ),
        lambda call: ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
        ),
    )

    with pytest.raises(ToolArgumentError) as error:
        ToolExecutor(registry).execute(_tool_call("nested.submit", {"payload": payload}))

    assert "arguments.payload.items[0]" in str(error.value)
    assert expected_detail in str(error.value)
    assert "do-not-echo" not in str(error.value)


def test_tool_executor_rejects_boolean_for_integer_and_accepts_integer_boundary() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolContract(
            name="bounded.submit",
            required_arguments=("count",),
            argument_properties={"count": {"type": "integer", "minimum": 1}},
        ),
        lambda call: ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
        ),
    )
    executor = ToolExecutor(registry)

    assert (
        executor.execute(_tool_call("bounded.submit", {"count": 1})).status
        is ToolCallStatus.EXECUTED
    )
    with pytest.raises(ToolArgumentError, match="expected integer"):
        executor.execute(_tool_call("bounded.submit", {"count": True}))


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

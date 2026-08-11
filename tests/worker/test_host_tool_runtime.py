from datetime import UTC, datetime

import pytest
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_integrations.host_tools import HostToolManifest
from zebra_agent_worker.tool_gateway_runtime import WorkerToolGateway


class _Local:
    model_tools = ()
    effective_mcp_tools = ()
    effective_skill_components = ()
    parallel_safe_tools = frozenset()
    parallel_batch_limits = {}

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls += 1
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="local",
        )

    def resolve_model_tool_calls(self, calls):
        return calls

    def close(self) -> None:
        pass


class _Host:
    def __init__(self) -> None:
        self.resource = None

    def invoke(self, tool_call, context, *, idempotency_key, required_resource, manifest):
        del tool_call, context, idempotency_key, manifest
        self.resource = required_resource
        return ToolResult(
            tool_call_id=new_tool_call_id(),
            status=ToolCallStatus.EXECUTED,
            output="host",
        )


def _context() -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-1",
        host_app_id="trench",
        namespace_id="tenant-a",
        workspace_ref="workspace-a",
        resource_refs=(HostResourceRef(type="trench.event", id="evt-1"),),
        scopes=("event.read",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300,
            max_model_tokens=100_000,
            max_artifact_bytes=10_485_760,
        ),
        origin="https://trench.example.com",
        policy_version="policy-v1",
    )


def test_worker_gateway_exposes_manifest_and_routes_host_resource() -> None:
    manifest = HostToolManifest.from_payload(
        {
            "workloadIdentity": "zebra-worker",
            "tools": [
                {
                    "name": "events.get_event",
                    "description": "Read one event",
                    "executionLocation": "host",
                    "scopes": ["event.read"],
                    "risk": "read",
                    "requiredArguments": ["event_id"],
                    "argumentProperties": {"event_id": {"type": "string"}},
                }
            ],
        }
    )
    host = _Host()
    gateway = WorkerToolGateway(
        local=_Local(),
        host=host,
        host_context=_context(),
        host_manifest=manifest,
    )
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="events.get_event",
        arguments={"event_id": "evt-1"},
        created_at=datetime.now(UTC),
    )

    result = gateway.execute(call)

    assert [tool.name for tool in gateway.model_tools] == ["events.get_event"]
    assert "events.get_event" in gateway.read_only_tools
    assert result.output == "host"
    assert host.resource == HostResourceRef(type="trench.event", id="evt-1")


def test_manifest_host_tool_never_falls_back_to_local() -> None:
    manifest = HostToolManifest.from_payload(
        {
            "workloadIdentity": "zebra-worker",
            "tools": [
                {
                    "name": "events.get_event",
                    "description": "Read one event",
                    "executionLocation": "host",
                    "scopes": ["event.read"],
                    "risk": "read",
                    "requiredArguments": ["event_id"],
                    "argumentProperties": {"event_id": {"type": "string"}},
                }
            ],
        }
    )
    local = _Local()
    gateway = WorkerToolGateway(
        local=local,
        host=None,
        host_context=_context(),
        host_manifest=manifest,
    )
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="events.get_event",
        arguments={"event_id": "evt-1"},
        created_at=datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="gateway is unavailable"):
        gateway.execute(call)
    assert local.calls == 0

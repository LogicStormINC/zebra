"""Neutral source fixture; signed transport and actual storage are composed by callers."""

from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from agent_integrations.host_tools.contracts import HostWorkloadIdentity
from agent_integrations.host_tools.gateway import HostToolGateway

from tests.agent_integrations.test_coverage_snapshot_v2 import V2_SOURCE, NeutralWire, manifest_v2


def setup_neutral_source(bodies=(b"hello",), *, session_id, authority, contract, now):
    wire = NeutralWire(bodies, contract=contract, authority=authority)
    gateway = HostToolGateway(
        authority.origin,
        HostWorkloadIdentity("worker", authority.namespace_id, authority.host_app_id),
        shared_secret="fixture-secret", transport=wire,
    )

    def admitted(call, context, **kwargs):
        response = wire.request(
            "POST", authority.origin, headers={"X-Zebra-Host-Auth": "admitted-fixture"},
            body={"toolName": call.name, "arguments": call.arguments}, timeout_seconds=30,
        )
        return ToolResult(
            tool_call_id=call.tool_call_id, status=ToolCallStatus.EXECUTED,
            output=response.body["output"],
        )

    return HostCoverageSnapshotSource(
        session_id=session_id, authority=authority, contract=contract, source_ref=V2_SOURCE,
        manifest=manifest_v2(), invoke=gateway.invoke, admitted_effect_invoke=admitted, now=now,
    ), wire

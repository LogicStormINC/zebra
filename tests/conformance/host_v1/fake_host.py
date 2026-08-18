"""In-process fake Hosts for the v1 conformance kit.

``fake_host_a`` speaks the trench-style read vocabulary; ``fake_host_b``
speaks a completely different business vocabulary. Both drive the REAL
wire parsing, resource binding resolution, invocation admission and effect
reconciliation paths — the shared suite proves Zebra treats them
identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.tools import ToolCall
from agent_integrations.host_tools.contracts import (
    HostToolGatewayError,
    HostToolInvocation,
    HostToolManifest,
    HostWorkloadIdentity,
)
from zebra_agent_worker.resource_binding import resolve_required_resource

# entry = (tool, capability, grant_scope, resource_type, argument, write)
HOST_A_TOOLS = (
    (
        "events.get_event",
        "evidence.read",
        "trench:event:read",
        "trench.event",
        "event_id",
        False,
    ),
    (
        "events.get_timeline",
        "timeline.read",
        "trench:timeline:read",
        "trench.entity",
        "entity",
        False,
    ),
    (
        "events.append_note",
        "note.write",
        "trench:note:write",
        "trench.event",
        "event_id",
        True,
    ),
)

HOST_B_TOOLS = (
    (
        "catalog.get_item",
        "catalog.item.read",
        "jazz:catalog:item:read",
        "catalog.item",
        "item_id",
        False,
    ),
    (
        "workflow.get_run",
        "workflow.read",
        "jazz:workflow:read",
        "workflow.run",
        "run_id",
        False,
    ),
    (
        "workflow.append_note",
        "workflow.note.write",
        "jazz:workflow:note:write",
        "workflow.note",
        "note_id",
        True,
    ),
)


@dataclass
class FakeHost:
    """One fake Host with its own vocabulary and business snapshot."""

    host_app_id: str
    namespace_id: str
    tools: tuple[tuple[str, str, str, str, str, bool], ...]
    business_snapshot: dict[str, str] = field(default_factory=dict)
    reconcile_outcomes: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    simulated_write_timeouts: set[str] = field(default_factory=set)

    def manifest_payload(self) -> dict[str, Any]:
        return {
            "workloadIdentity": "zebra-worker",
            "tools": [
                {
                    "name": tool,
                    "description": f"{tool} on {self.host_app_id}",
                    "requiredArguments": [argument],
                    "argumentProperties": {argument: {"type": "string"}},
                    "scopes": [grant_scope],
                    "risk": "write" if write else "read",
                    "resourceBindings": [
                        {
                            "argumentPointer": f"/{argument}",
                            "resourceType": resource_type,
                            "required": True,
                            "matchMode": "exact",
                        }
                    ],
                }
                for tool, _capability, grant_scope, resource_type, argument, write in self.tools
            ],
        }

    def manifest(self) -> HostToolManifest:
        return HostToolManifest.from_payload(self.manifest_payload())

    def grant_context(
        self,
        *,
        scopes: tuple[str, ...],
        resources: tuple[HostResourceRef, ...],
    ) -> HostContextEnvelope:
        return HostContextEnvelope(
            grant_id="grant-1",
            host_app_id=self.host_app_id,
            namespace_id=self.namespace_id,
            workspace_ref="workspace-1",
            resource_refs=resources,
            scopes=scopes,
            limits=HostTechnicalLimits(
                max_runtime_seconds=300,
                max_model_tokens=100_000,
                max_artifact_bytes=10_485_760,
            ),
            origin=f"https://{self.host_app_id}.example.com",
            policy_version="policy-v1",
        )

    def full_grant(self) -> HostContextEnvelope:
        scopes = tuple({scope for _t, _c, scope, *_ in self.tools} | {"host:extra"})
        seen_types: set[str] = set()
        resources = []
        for _tool, _cap, _scope, resource_type, _arg, _write in self.tools:
            if resource_type in seen_types:
                continue
            seen_types.add(resource_type)
            resources.append(HostResourceRef(type=resource_type, id=f"{resource_type}-1"))
        return self.grant_context(scopes=scopes, resources=tuple(resources))

    def invoke_drifted(self, tool_call: ToolCall, context: HostContextEnvelope) -> str:
        """Invoke with the Worker identity pinned to the ORIGINAL namespace.

        The drifted grant namespace no longer matches the workload identity,
        which is exactly the namespace-mismatch denial the kit must prove.
        """

        manifest = self.manifest()
        contract = manifest.get(tool_call.name)
        if contract is None:
            raise HostToolGatewayError("unknown tool for this Host", reason="unknown_tool")
        from agent_integrations.host_tools.contracts import HostWorkloadIdentity

        identity = HostWorkloadIdentity(
            "zebra-worker",
            self.namespace_id,
            self.host_app_id,
        )
        from agent_integrations.host_tools.contracts import HostToolInvocation

        HostToolInvocation(
            tool_call=tool_call,
            contract=contract,
            context=context,
            identity=identity,
            effective_scopes=context.scopes,
            required_resource=resolve_required_resource(
                manifest.resource_bindings_for(tool_call.name),
                tool_call,
                context,
            ),
        )
        return "unreachable"

    def read_tool(self) -> tuple[str, str, str]:
        entry = next(item for item in self.tools if not item[5])
        return entry[0], entry[3], entry[4]

    def write_tool(self) -> tuple[str, str, str]:
        entry = next(item for item in self.tools if item[5])
        return entry[0], entry[3], entry[4]

    def invoke(self, tool_call: ToolCall, context: HostContextEnvelope) -> str:
        """Run the REAL admission chain; admitted writes hit the snapshot."""

        manifest = self.manifest()
        contract = manifest.get(tool_call.name)
        if contract is None:
            raise HostToolGatewayError("unknown tool for this Host", reason="unknown_tool")
        resource = resolve_required_resource(
            manifest.resource_bindings_for(tool_call.name),
            tool_call,
            context,
        )
        HostToolInvocation(
            tool_call=tool_call,
            contract=contract,
            context=context,
            identity=HostWorkloadIdentity(
                "zebra-worker",
                context.namespace_id,
                context.host_app_id,
            ),
            effective_scopes=context.scopes,
            required_resource=resource,
            idempotency_key=f"conf:{tool_call.tool_call_id}",
        )
        write_entry = next(
            (item for item in self.tools if item[0] == tool_call.name and item[5]), None
        )
        if write_entry is None:
            return "read-acknowledged"
        if tool_call.name in self.simulated_write_timeouts:
            return "uncertain"
        argument = write_entry[4]
        key = str(tool_call.arguments.get(argument, "unknown"))
        self.business_snapshot[f"{tool_call.name}:{key}"] = "written"
        return "written"


def host_a() -> FakeHost:
    return FakeHost(
        host_app_id="conf-host-a",
        namespace_id="tenant-a",
        tools=HOST_A_TOOLS,
    )


def host_b() -> FakeHost:
    return FakeHost(
        host_app_id="conf-host-b",
        namespace_id="tenant-b",
        tools=HOST_B_TOOLS,
    )


CONFORMANCE_HOSTS = (host_a, host_b)

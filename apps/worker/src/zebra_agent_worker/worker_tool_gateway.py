"""Tool routing and execution resource ownership for one Worker attempt."""

from dataclasses import dataclass

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.host_effect_receipts import HostEffectReceipt
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import (
    ToolCall,
    ToolCallStatus,
    ToolIdempotency,
    ToolResult,
    ToolRisk,
)
from agent_core.harness.models import SkillReadRequirement
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_integrations.host_tools import (
    HostToolGateway,
    HostToolManifest,
)
from agent_runtime import LocalToolGateway
from agent_runtime.deferred import DeferredRuntime
from agent_tools.extension_management import (
    READ_NAMES,
    WRITE_NAMES,
    ExtensionManagementTools,
    management_contracts,
)
from agent_tools.native_script import NativeScriptTools
from agent_tools.registry import ToolRegistry

from zebra_agent_worker.client_tool_gateway import ClientToolGateway
from zebra_agent_worker.host_media_artifacts import (
    HostMediaArtifactImporter,
    has_host_media_envelope,
)
from zebra_agent_worker.resource_binding import resolve_required_resource
from zebra_agent_worker.tool_gateway_reachability import (
    available_host_tools as _available_host_tools,
)
from zebra_agent_worker.tool_gateway_reachability import (
    host_model_tools as _host_model_tools,
)

NETWORKED_WEB_TOOLS = frozenset({"web.fetch", "web.search", "web.crawl", "web.extract"})
NATIVE_WEB_READ_TOOLS = frozenset({"web.crawl", "web.extract", "web.read", "web.find"})
WEB_ALLOWED_PROFILES = frozenset({"domain-allowlist", "full-gateway", "full-trusted-local"})


@dataclass
class WorkerToolGateway:
    """Compose local tools with a manifest-bound Host gateway."""

    local: LocalToolGateway
    web_egress_enabled: bool = True
    web_pipeline_v2: bool = False
    host: HostToolGateway | None = None
    host_context: HostContextEnvelope | None = None
    host_manifest: HostToolManifest | None = None
    runtime: RuntimePort | None = None
    runtime_handle: RuntimeHandle | None = None
    client: ClientToolGateway | None = None
    management: ExtensionManagementTools | None = None
    management_names: frozenset[str] = frozenset()
    resource_authority_issuer: str | None = None
    host_media_importer: HostMediaArtifactImporter | None = None
    native_scripts: NativeScriptTools | None = None

    @property
    def model_tools(self) -> tuple[ModelToolDefinition, ...]:
        tools = self.local.model_tools
        if not self.web_egress_enabled:
            tools = tuple(tool for tool in tools if tool.name not in NETWORKED_WEB_TOOLS)
        if self.native_scripts is not None:
            tools += self.native_scripts.registry.model_tools()
        tools += _host_model_tools(self.host_manifest, self.host_context)
        if self.management is not None:
            registry = ToolRegistry()
            for contract in management_contracts():
                if contract.name in self.management_names:
                    registry.register(contract, self.management.execute)
            tools += registry.model_tools()
        client_gateway = self.client
        if client_gateway is not None:
            tools = tools + tuple(client_gateway.model_tools)
        return tools

    @property
    def effective_mcp_tools(self) -> tuple[ModelToolDefinition, ...]:
        return self.local.effective_mcp_tools

    @property
    def effective_skill_components(self) -> tuple[str, ...]:
        return self.local.effective_skill_components

    @property
    def effective_skill_requirements(self) -> tuple[SkillReadRequirement, ...]:
        return self.local.effective_skill_requirements

    @property
    def parallel_safe_tools(self) -> frozenset[str]:
        host_safe = (
            frozenset(
                tool.name
                for tool in _available_host_tools(self.host_manifest, self.host_context)
                if tool.parallel_safe
            )
            if self.host_manifest is not None
            else frozenset()
        )
        client_safe = (
            frozenset(self.client.parallel_safe_tools) if self.client is not None else frozenset()
        )
        return self.local.parallel_safe_tools | host_safe | client_safe

    @property
    def parallel_batch_limits(self) -> dict[str, int]:
        return self.local.parallel_batch_limits

    @property
    def read_only_tools(self) -> frozenset[str]:
        host_read = (
            frozenset(
                tool.name
                for tool in _available_host_tools(self.host_manifest, self.host_context)
                if tool.risk is ToolRisk.READ
            )
            if self.host_manifest is not None
            else frozenset()
        )
        from agent_tools.effect_guard_support import READ_ONLY_TOOLS

        native_read = NATIVE_WEB_READ_TOOLS if self.web_pipeline_v2 else frozenset()
        scripts = self.native_scripts.names if self.native_scripts is not None else frozenset()
        return (
            READ_ONLY_TOOLS
            | native_read
            | host_read
            | scripts
            | (self.management_names & READ_NAMES)
        )

    @property
    def mutation_tools(self) -> frozenset[str]:
        host_writes = (
            frozenset(
                tool.name
                for tool in _available_host_tools(self.host_manifest, self.host_context)
                if tool.risk is ToolRisk.WRITE
            )
            if self.host_manifest is not None
            else frozenset()
        )
        return host_writes | (self.management_names & WRITE_NAMES)

    @property
    def authorized_write_tools(self) -> frozenset[str]:
        management_write = self.management_names & WRITE_NAMES
        client_tools = self.client.authorized_policy_tools if self.client else frozenset()
        if self.host_manifest is None or self.host_context is None:
            return management_write | client_tools
        granted_scopes = frozenset(self.host_context.scopes)
        host_tools = frozenset(
            tool.name
            for tool in _available_host_tools(self.host_manifest, self.host_context)
            if tool.risk is ToolRisk.WRITE and frozenset(tool.scopes) <= granted_scopes
        )
        return management_write | client_tools | host_tools

    @property
    def approval_tools(self) -> frozenset[str]:
        client_tools = self.client.approval_required_tools if self.client else frozenset()
        if self.host_manifest is None:
            return client_tools
        return client_tools | frozenset(
            tool.name
            for tool in _available_host_tools(self.host_manifest, self.host_context)
            if tool.risk is not ToolRisk.READ
        )

    @property
    def approval_required_tools(self) -> frozenset[str]:
        return self.approval_tools - self.authorized_write_tools

    def resolve_model_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> tuple[ToolCall, ...]:
        return self.local.resolve_model_tool_calls(tool_calls)

    def reconcile_effect_receipt(self, receipt: HostEffectReceipt) -> HostEffectReceipt:
        if self.host is None or self.host_context is None:
            return receipt
        return self.host.reconcile_effect(receipt, self.host_context)

    def reconcile_deferred_result(self, call: ToolCall, original: ToolResult) -> ToolResult | None:
        if self.client is None:
            return None
        return self.client.reconcile_deferred_result(call, original)

    def execute(self, toolCall: ToolCall) -> ToolResult:
        return self._execute(toolCall)

    def _execute(self, tool_call: ToolCall) -> ToolResult:
        if self.native_scripts is not None and tool_call.name in self.native_scripts.names:
            return self.native_scripts.execute(tool_call)
        if self.management is not None and tool_call.name in self.management_names:
            return self.management.execute(tool_call)
        if self.client is not None and tool_call.name in {
            tool.name for tool in self.client.model_tools
        }:
            return self.client.execute(tool_call)
        host_manifest = self.host_manifest
        host_names = (
            {tool.name for tool in host_manifest.tools} if host_manifest is not None else set()
        )
        if tool_call.name not in host_names:
            return self.local.execute(tool_call)
        if self.host is None:
            raise ValueError("Host Tool gateway is unavailable")
        if self.host_context is None:
            raise ValueError("Host Tool context is unavailable")
        if host_manifest is None:
            raise ValueError("Host Tool manifest is unavailable")
        contract = host_manifest.get(tool_call.name)
        assert contract is not None
        idempotency_key = (
            f"host:{tool_call.tool_call_id}"
            if contract.idempotency is ToolIdempotency.REQUIRED
            else None
        )
        required_resource = resolve_required_resource(
            host_manifest.resource_bindings_for(tool_call.name),
            tool_call,
            self.host_context,
        )
        result = self.host.invoke(
            tool_call,
            self.host_context,
            idempotency_key=idempotency_key,
            required_resource=required_resource,
            manifest=self.host_manifest,
        )
        if result.status is ToolCallStatus.EXECUTED and has_host_media_envelope(result):
            if self.host_media_importer is None:
                return result.model_copy(
                    update={
                        "status": ToolCallStatus.FAILED,
                        "output": "Host media import is unavailable for this Session.",
                        "metadata": {**result.metadata, "reason": "artifact_publish_unavailable"},
                    }
                )
            result = self.host_media_importer.materialize(result)
        if required_resource is None or self.resource_authority_issuer is None:
            return result
        from agent_core.domain.verification_evidence import VerificationResourceRef

        resource_ref = VerificationResourceRef(
            authority_issuer=self.resource_authority_issuer,
            namespace_id=self.host_context.namespace_id,
            host_app_id=self.host_context.host_app_id,
            resource_type=required_resource.resource_type,
            resource_id=required_resource.resource_id,
        )
        return result.model_copy(
            update={
                "metadata": {
                    **result.metadata,
                    "verification_resource_ref": resource_ref.model_dump(mode="json"),
                }
            }
        )

    def close(self) -> None:
        try:
            self.local.close()
        finally:
            if isinstance(self.runtime, DeferredRuntime):
                self.runtime.close()
            elif self.runtime is not None and self.runtime_handle is not None:
                handle = self.runtime_handle
                self.runtime_handle = None
                self.runtime.destroy(handle)

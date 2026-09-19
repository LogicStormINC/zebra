"""Worker-local tool gateway composition."""

from dataclasses import dataclass

from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCall, ToolIdempotency, ToolResult, ToolRisk
from agent_core.harness.models import SkillReadRequirement
from agent_core.ports import (
    ArtifactPayloadStorePort,
    ModelGatewayPort,
    SessionHistoryPort,
)
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_core.ports.host_credential_resolver import HostWorkloadCredentialResolverPort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver
from agent_integrations.host_tools import (
    HostToolGateway,
    HostToolManifest,
    HostWorkloadIdentity,
)
from agent_runtime import LocalToolGateway
from agent_runtime.cloud_mcp_transport import CloudMcpTransport
from agent_storage import SQLiteSkillsStateStore
from agent_tools.extension_management import (
    READ_NAMES,
    WRITE_NAMES,
    ExtensionManagementTools,
    management_contracts,
)
from agent_tools.registry import ToolRegistry
from agent_tools.skills_catalog import SkillCatalog
from agent_tools.skills_scope import build_scoped_skill_roots
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.client_tool_gateway import ClientToolGateway
from zebra_agent_worker.resource_binding import resolve_required_resource
from zebra_agent_worker.task_recovery import RecoveredTask
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator


@dataclass
class WorkerToolGateway:
    """Compose local tools with a manifest-bound Host gateway."""

    local: LocalToolGateway
    host: HostToolGateway | None = None
    host_context: HostContextEnvelope | None = None
    host_manifest: HostToolManifest | None = None
    runtime: RuntimePort | None = None
    runtime_handle: RuntimeHandle | None = None
    client: ClientToolGateway | None = None
    management: ExtensionManagementTools | None = None
    management_names: frozenset[str] = frozenset()
    resource_authority_issuer: str | None = None

    @property
    def model_tools(self) -> tuple[ModelToolDefinition, ...]:
        tools = self.local.model_tools + _host_model_tools(self.host_manifest)
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
            frozenset(tool.name for tool in self.host_manifest.tools if tool.parallel_safe)
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
            frozenset(tool.name for tool in self.host_manifest.tools if tool.risk is ToolRisk.READ)
            if self.host_manifest is not None
            else frozenset()
        )
        from agent_tools.effect_guard_support import READ_ONLY_TOOLS

        return READ_ONLY_TOOLS | host_read | (self.management_names & READ_NAMES)

    @property
    def mutation_tools(self) -> frozenset[str]:
        host_writes = (
            frozenset(tool.name for tool in self.host_manifest.tools if tool.risk is ToolRisk.WRITE)
            if self.host_manifest is not None
            else frozenset()
        )
        return host_writes | (self.management_names & WRITE_NAMES)

    @property
    def authorized_write_tools(self) -> frozenset[str]:
        management_write = self.management_names & WRITE_NAMES
        if self.host_manifest is None or self.host_context is None:
            return management_write
        granted_scopes = frozenset(self.host_context.scopes)
        return management_write | frozenset(
            tool.name
            for tool in self.host_manifest.tools
            if tool.risk is ToolRisk.WRITE and frozenset(tool.scopes) <= granted_scopes
        )

    @property
    def approval_tools(self) -> frozenset[str]:
        if self.host_manifest is None:
            return frozenset()
        return frozenset(
            tool.name for tool in self.host_manifest.tools if tool.risk is not ToolRisk.READ
        )

    @property
    def approval_required_tools(self) -> frozenset[str]:
        return self.approval_tools - self.authorized_write_tools

    def resolve_model_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> tuple[ToolCall, ...]:
        return self.local.resolve_model_tool_calls(tool_calls)

    def execute(self, toolCall: ToolCall) -> ToolResult:
        return self._execute(toolCall)

    def _execute(self, tool_call: ToolCall) -> ToolResult:
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
            if self.runtime is not None and self.runtime_handle is not None:
                handle = self.runtime_handle
                self.runtime_handle = None
                self.runtime.destroy(handle)


def build_worker_tool_gateway(
    task: RecoveredTask,
    *,
    settings: ZebraAgentSettings,
    model_gateway: ModelGatewayPort,
    session_history: SessionHistoryPort,
    session_id: SessionId,
    runtime: RuntimePort,
    runtime_handle: RuntimeHandle,
    local_artifacts: ArtifactPayloadStorePort | None,
    cloud_artifacts: CloudToolOutputArtifactCoordinator | None,
    trusted_local: bool,
    durable_delegation: bool = False,
    egress_registry: HostConnectorRegistryPort | None = None,
    delegation_store: object | None = None,
    parent_task_id: object | None = None,
    parent_binding_digest: str | None = None,
    parent_binding: object | None = None,
    parent_context: ContextMaterialization | None = None,
    manifest_digest: str | None = None,
    frozen_manifest_loader: object = None,
    client_gateway: ClientToolGateway | None = None,
    skill_catalog: SkillCatalog | None = None,
    skill_component_names: tuple[str, ...] = (),
    cloud_mcp_transport: CloudMcpTransport | None = None,
    resource_authority_issuer: str | None = None,
) -> WorkerToolGateway:
    can_publish = (
        cloud_artifacts is not None
        and task.host_context is not None
        and "artifact.publish" in task.host_context.scopes
    )
    skill_roots = build_scoped_skill_roots(
        system=settings.skill_roots_system,
        admin=settings.skill_roots_admin,
        user=settings.skill_roots,
        repo=settings.skill_roots_repo,
    )
    skills_enabled = any(
        (
            settings.skill_roots,
            settings.skill_roots_system,
            settings.skill_roots_admin,
            settings.skill_roots_repo,
        )
    )
    cloud_mcp = cloud_mcp_transport is not None or settings.mcp_credentials.worker_enabled
    local = LocalToolGateway(
        task.workspace_root,
        model_gateway=model_gateway,
        tool_profile=task.tool_profile,
        web_search_endpoint=settings.web_search_endpoint,
        skill_roots=() if skill_catalog is not None else skill_roots,
        skill_catalog=skill_catalog,
        skill_component_names=skill_component_names,
        skills_state=(
            SQLiteSkillsStateStore(settings.skills_state_path)
            if skills_enabled and skill_catalog is None
            else None
        ),
        mcp_servers=() if cloud_mcp else settings.mcp_servers,
        mcp_allowlist=() if cloud_mcp else task.mcp_allowlist,
        cloud_mcp_transport=cloud_mcp_transport,
        session_history=session_history.scoped(task.history_session_ids),
        current_session_id=str(session_id),
        runtime=runtime,
        runtime_handle=None,
        artifact_payload_store=local_artifacts if cloud_artifacts is None else None,
        output_projector=cloud_artifacts.output_projector if cloud_artifacts else None,
        file_publisher=(
            cloud_artifacts.capture_file if can_publish and cloud_artifacts is not None else None
        ),
        max_publish_bytes=(
            task.host_context.limits.max_artifact_bytes
            if can_publish and task.host_context is not None
            else 0
        ),
        trusted_local=trusted_local,
        web_pipeline_v2=settings.web_pipeline_v2,
        durable_delegation=durable_delegation,
        delegation_store=delegation_store,
        parent_task_id=parent_task_id,
        parent_binding_digest=parent_binding_digest,
        parent_binding=parent_binding,
        parent_context=parent_context,
    )
    if task.host_context is None:
        return WorkerToolGateway(
            local=local,
            runtime=runtime,
            runtime_handle=runtime_handle,
            client=client_gateway,
            resource_authority_issuer=resource_authority_issuer,
        )
    credential_resolver = (
        ConfiguredHmacHostCredentialResolver(settings.host_tool_shared_secret)
        if settings.host_tool_shared_secret
        else None
    )
    pinned = _resolve_pinned_gateway(
        task.host_context,
        egress_registry,
        credential_resolver,
    )
    if pinned is not None:
        try:
            manifest = _frozen_or_discovered_manifest(
                pinned,
                task.host_context,
                manifest_digest,
                frozen_manifest_loader,
            )
            local_names = {tool.name for tool in local.model_tools}
            host_names = {tool.name for tool in manifest.tools}
            overlap = local_names & host_names
            if overlap:
                raise ValueError(
                    f"Host Tool names overlap local tools: {', '.join(sorted(overlap))}"
                )
        except Exception:
            local.close()
            raise
        return WorkerToolGateway(
            local=local,
            host=pinned,
            host_context=task.host_context,
            host_manifest=manifest,
            runtime=runtime,
            runtime_handle=runtime_handle,
            client=client_gateway,
            resource_authority_issuer=resource_authority_issuer,
        )
    if manifest_digest and manifest_digest != _NO_MANIFEST_DIGEST:
        # The binding froze a real Host manifest, yet no pinned connector
        # resolves for this namespace — inconsistent state fails closed.
        local.close()
        raise ValueError(
            "binding references a frozen Host manifest but no pinned "
            "connector resolves; failing closed"
        )
    if not settings.host_tool_endpoint or not settings.host_tool_workload_identity:
        # No pinned connector and no legacy egress config: the admission
        # binding froze NO Host manifest (placeholder digest), so the
        # session's contract is a local-only tool surface.
        return WorkerToolGateway(
            local=local,
            runtime=runtime,
            runtime_handle=runtime_handle,
            client=client_gateway,
            resource_authority_issuer=resource_authority_issuer,
        )
    if not settings.host_tool_shared_secret:
        local.close()
        raise ValueError("Host Tool shared secret is required")
    identity = HostWorkloadIdentity(
        settings.host_tool_workload_identity,
        task.host_context.namespace_id,
        task.host_context.host_app_id,
    )
    host = HostToolGateway(
        settings.host_tool_endpoint,
        identity,
        shared_secret=settings.host_tool_shared_secret,
    )
    try:
        manifest = host.discover(task.host_context)
        local_names = {tool.name for tool in local.model_tools}
        host_names = {tool.name for tool in manifest.tools}
        overlap = local_names & host_names
        if overlap:
            raise ValueError(f"Host Tool names overlap local tools: {', '.join(sorted(overlap))}")
    except Exception:
        local.close()
        raise
    return WorkerToolGateway(
        local=local,
        host=host,
        host_context=task.host_context,
        host_manifest=manifest,
        runtime=runtime,
        runtime_handle=runtime_handle,
        client=client_gateway,
        resource_authority_issuer=resource_authority_issuer,
    )


_NO_MANIFEST_DIGEST = "0" * 64


def _frozen_or_discovered_manifest(
    pinned: HostToolGateway,
    host_context: HostContextEnvelope,
    manifest_digest: str | None,
    frozen_manifest_loader: object,
) -> HostToolManifest:
    """ADR-017 execution freeze: bindings frozen at admission consume the
    STORED manifest — never a live discovery. Placeholder-digest sessions
    (admitted before the freeze, or unbound) keep the legacy discovery.
    Missing or drifted freezes fail closed.
    """

    if manifest_digest is None or manifest_digest == _NO_MANIFEST_DIGEST:
        return pinned.discover(host_context)
    if not callable(frozen_manifest_loader):
        raise ValueError(
            "binding carries a frozen manifest digest but no loader is wired; failing closed"
        )
    frozen = frozen_manifest_loader(manifest_digest)
    if not isinstance(frozen, dict):
        raise ValueError("frozen Host manifest is missing; failing closed")
    from agent_integrations.host_tools.contracts import HostToolManifest

    manifest = HostToolManifest.from_payload(frozen)
    if manifest.digest != manifest_digest:
        raise ValueError("frozen Host manifest digest drifted; failing closed")
    object.__setattr__(pinned, "manifest", manifest)
    return manifest


def _resolve_pinned_gateway(
    host_context: HostContextEnvelope,
    egress_registry: HostConnectorRegistryPort | None,
    credential_resolver: HostWorkloadCredentialResolverPort | None,
) -> HostToolGateway | None:
    """Phase F2: pinned profile egress when a connector binding exists.

    Returns None when no registry is wired or no binding matches (legacy
    env fallback); revoked or missing profiles fail closed.
    """

    if egress_registry is None:
        return None
    from zebra_agent_worker.host_egress import (
        HostEgressResolver,
        build_pinned_host_gateway,
    )

    assert egress_registry is not None
    resolver = HostEgressResolver(egress_registry, credential_resolver)
    pinned = resolver.resolve(host_context)
    if pinned is None:
        return None
    if credential_resolver is None:
        raise ValueError(
            "pinned connector requires a configured Host workload credential; failing closed"
        )
    credential = resolver.issue_credential(pinned, host_context)
    return build_pinned_host_gateway(pinned, host_context, credential)


def _host_model_tools(manifest: HostToolManifest | None) -> tuple[ModelToolDefinition, ...]:
    if manifest is None:
        return ()
    return tuple(
        ModelToolDefinition(
            name=tool.name,
            description=tool.description,
            parameters={
                "type": "object",
                "properties": {key: dict(value) for key, value in tool.argument_properties.items()},
                "required": list(tool.required_arguments),
                "additionalProperties": False,
            },
        )
        for tool in manifest.tools
    )

"""Worker-local tool gateway composition."""

from dataclasses import dataclass

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.tools import ToolCall, ToolIdempotency, ToolResult, ToolRisk
from agent_core.ports import ArtifactPayloadStorePort, ModelGatewayPort, SessionHistoryPort
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_integrations.host_tools import HostToolGateway, HostToolManifest, HostWorkloadIdentity
from agent_runtime import LocalToolGateway
from agent_storage import SQLiteSkillsStateStore
from agent_tools.skills_scope import build_scoped_skill_roots
from zebra_agent_config import ZebraAgentSettings

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

    @property
    def model_tools(self) -> tuple[ModelToolDefinition, ...]:
        return self.local.model_tools + _host_model_tools(self.host_manifest)

    @property
    def effective_mcp_tools(self) -> tuple[ModelToolDefinition, ...]:
        return self.local.effective_mcp_tools

    @property
    def effective_skill_components(self) -> tuple[str, ...]:
        return self.local.effective_skill_components

    @property
    def parallel_safe_tools(self) -> frozenset[str]:
        host_safe = (
            frozenset(tool.name for tool in self.host_manifest.tools if tool.parallel_safe)
            if self.host_manifest is not None
            else frozenset()
        )
        return self.local.parallel_safe_tools | host_safe

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

        return READ_ONLY_TOOLS | host_read

    def resolve_model_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> tuple[ToolCall, ...]:
        return self.local.resolve_model_tool_calls(tool_calls)

    def execute(self, tool_call: ToolCall) -> ToolResult:
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
        return self.host.invoke(
            tool_call,
            self.host_context,
            idempotency_key=idempotency_key,
            required_resource=resolve_required_resource(
                host_manifest.resource_bindings_for(tool_call.name),
                tool_call,
                self.host_context,
            ),
            manifest=self.host_manifest,
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
) -> WorkerToolGateway:
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
    local = LocalToolGateway(
        task.workspace_root,
        model_gateway=model_gateway,
        tool_profile=task.tool_profile,
        web_search_endpoint=settings.web_search_endpoint,
        skill_roots=skill_roots,
        skills_state=(
            SQLiteSkillsStateStore(settings.skills_state_path) if skills_enabled else None
        ),
        mcp_servers=settings.mcp_servers,
        mcp_allowlist=task.mcp_allowlist,
        session_history=session_history.scoped(task.history_session_ids),
        current_session_id=str(session_id),
        runtime=runtime,
        runtime_handle=None,
        artifact_payload_store=local_artifacts if cloud_artifacts is None else None,
        output_projector=cloud_artifacts.output_projector if cloud_artifacts else None,
        trusted_local=trusted_local,
        web_pipeline_v2=settings.web_pipeline_v2,
        durable_delegation=durable_delegation,
    )
    if task.host_context is None:
        return WorkerToolGateway(
            local=local,
            runtime=runtime,
            runtime_handle=runtime_handle,
        )
    pinned = _resolve_pinned_gateway(task.host_context, egress_registry)
    if pinned is not None:
        try:
            manifest = pinned.discover(task.host_context)
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
        )
    if not settings.host_tool_endpoint or not settings.host_tool_workload_identity:
        local.close()
        raise ValueError("Host Tool endpoint and workload identity are required")
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
    )


def _resolve_pinned_gateway(
    host_context: HostContextEnvelope,
    egress_registry: HostConnectorRegistryPort | None,
) -> HostToolGateway | None:
    """Phase F2: pinned profile egress when a connector binding exists.

    Returns None when no registry is wired or no binding matches (legacy
    env fallback); revoked or missing profiles fail closed.
    """

    if egress_registry is None:
        return None
    from agent_core.ports.host_credential_resolver import EphemeralHostCredential

    from zebra_agent_worker.host_egress import (
        HostEgressResolver,
        build_pinned_host_gateway,
    )

    class _CompatCredentials:
        def issue(
            self,
            *,
            credential_ref: str,
            workload_identity_ref: str,
            audience: str,
            scopes: tuple[str, ...],
            ttl_seconds: int,
        ) -> EphemeralHostCredential:
            from datetime import UTC, datetime

            return EphemeralHostCredential(
                token=f"compat:{credential_ref}",
                audience=audience,
                scopes=tuple(scopes),
                expires_at_epoch=int(datetime.now(UTC).timestamp()) + ttl_seconds,
            )

    assert egress_registry is not None
    resolver = HostEgressResolver(egress_registry, _CompatCredentials())
    pinned = resolver.resolve(host_context)
    if pinned is None:
        return None
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

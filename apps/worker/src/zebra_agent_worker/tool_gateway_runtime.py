from collections.abc import Callable

from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.domain.identifiers import SessionId
from agent_core.ports import (
    ArtifactPayloadReadPort,
    ArtifactPayloadStorePort,
    ModelGatewayPort,
    SessionHistoryPort,
)
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver
from agent_integrations.host_tools import (
    HostToolGateway,
    HostWorkloadIdentity,
)
from agent_runtime import LocalToolGateway
from agent_runtime.cloud_mcp_transport import CloudMcpTransport
from agent_storage import SQLiteSkillsStateStore
from agent_tools.skills_catalog import SkillCatalog
from agent_tools.skills_scope import build_scoped_skill_roots
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.client_tool_gateway import ClientToolGateway
from zebra_agent_worker.host_gateway_resolution import (
    NO_MANIFEST_DIGEST,
    frozen_or_discovered_manifest,
    resolve_pinned_gateway,
)
from zebra_agent_worker.host_media_artifacts import (
    HostMediaArtifactImporter,
)
from zebra_agent_worker.task_recovery import RecoveredTask
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator
from zebra_agent_worker.worker_tool_gateway import WorkerToolGateway as WorkerToolGateway

NETWORKED_WEB_TOOLS = frozenset({"web.fetch", "web.search", "web.crawl", "web.extract"})
NATIVE_WEB_READ_TOOLS = frozenset({"web.crawl", "web.extract", "web.read", "web.find"})
WEB_ALLOWED_PROFILES = frozenset({"domain-allowlist", "full-gateway", "full-trusted-local"})



def build_worker_tool_gateway(
    task: RecoveredTask,
    *,
    settings: ZebraAgentSettings,
    model_gateway: ModelGatewayPort,
    session_history: SessionHistoryPort,
    session_id: SessionId,
    runtime: RuntimePort,
    runtime_handle: RuntimeHandle | None,
    local_artifacts: ArtifactPayloadStorePort | None,
    artifact_payload_reader: ArtifactPayloadReadPort | None,
    cloud_artifacts: CloudToolOutputArtifactCoordinator | None,
    trusted_local: bool,
    durable_delegation: bool = False,
    egress_registry: HostConnectorRegistryPort | None = None,
    delegation_store: object | None = None,
    parent_task_id: object | None = None,
    parent_attempt_number: int = 1,
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
    network_cancellation_check: Callable[[], None] | None = None,
) -> WorkerToolGateway:
    can_publish = (
        cloud_artifacts is not None
        and task.host_context is not None
        and "artifact.publish" in task.host_context.scopes
    )
    host_media_importer = (
        HostMediaArtifactImporter(
            cloud_artifacts.capture_file,
            max_bytes=task.host_context.limits.max_artifact_bytes,
            # Fake-IP acceptance is a property of this runtime's network
            # resolver, not of the deployment profile. Cloud Workers may be
            # explicitly composed with the trusted-local runtime for local
            # integration while policy remains cloud-scoped.
            allow_fake_ip_dns=settings.runtime.runtime_class == "trusted-local",
        )
        if can_publish and cloud_artifacts is not None and task.host_context is not None
        else None
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
        web_search_private_backend=settings.web_search_private_backend,
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
        artifact_payload_reader=artifact_payload_reader,
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
        parent_attempt_number=parent_attempt_number,
        parent_binding_digest=parent_binding_digest,
        parent_binding=parent_binding,
        parent_context=parent_context,
        network_cancellation_check=network_cancellation_check,
        reuse_doh_transport=settings.deployment == "cloud",
        egress_endpoint=(settings.web_egress_socks_endpoint
                         if settings.deployment == "cloud" else None),
    )
    web_egress_enabled = trusted_local or task.network_profile.name.value in WEB_ALLOWED_PROFILES
    if task.host_context is None:
        return WorkerToolGateway(
            local=local,
            web_egress_enabled=web_egress_enabled,
            web_pipeline_v2=settings.web_pipeline_v2,
            runtime=runtime,
            runtime_handle=runtime_handle,
            client=client_gateway,
            resource_authority_issuer=resource_authority_issuer,
            host_media_importer=host_media_importer,
        )
    credential_resolver = (
        ConfiguredHmacHostCredentialResolver(settings.host_tool_shared_secret)
        if settings.host_tool_shared_secret
        else None
    )
    pinned = resolve_pinned_gateway(
        task.host_context,
        egress_registry,
        credential_resolver,
    )
    if pinned is not None:
        try:
            manifest = frozen_or_discovered_manifest(
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
            web_egress_enabled=web_egress_enabled,
            web_pipeline_v2=settings.web_pipeline_v2,
            host_context=task.host_context,
            host_manifest=manifest,
            runtime=runtime,
            runtime_handle=runtime_handle,
            client=client_gateway,
            resource_authority_issuer=resource_authority_issuer,
            host_media_importer=host_media_importer,
        )
    if manifest_digest and manifest_digest != NO_MANIFEST_DIGEST:
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
            web_egress_enabled=web_egress_enabled,
            web_pipeline_v2=settings.web_pipeline_v2,
            runtime_handle=runtime_handle,
            client=client_gateway,
            resource_authority_issuer=resource_authority_issuer,
            host_media_importer=host_media_importer,
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
        web_egress_enabled=web_egress_enabled,
        web_pipeline_v2=settings.web_pipeline_v2,
        host_context=task.host_context,
        host_manifest=manifest,
        runtime=runtime,
        runtime_handle=runtime_handle,
        client=client_gateway,
        resource_authority_issuer=resource_authority_issuer,
        host_media_importer=host_media_importer,
    )

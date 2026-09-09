"""Narrow tool-gateway composition extracted from the execution lifecycle."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx
from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports import ArtifactPayloadStorePort, ModelGatewayPort, SessionHistoryPort
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_integrations import ModelProviderSettings
from agent_tools.extension_management import READ_NAMES, WRITE_NAMES
from zebra_agent_config import ZebraAgentSettings

import zebra_agent_worker.worker_skill_catalog as worker_skills
from zebra_agent_worker.client_tool_gateway import ClientToolGateway
from zebra_agent_worker.extension_recovery import RecoveredTurnExtension, WorkerExtensionStore
from zebra_agent_worker.provider_configuration import model_provider_settings
from zebra_agent_worker.task_recovery import RecoveredTask
from zebra_agent_worker.tool_gateway_runtime import WorkerToolGateway, build_worker_tool_gateway
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator
from zebra_agent_worker.worker_extension_management import prepare_extension_management
from zebra_agent_worker.worker_mcp_catalog import WorkerMcpSource as WorkerMcpSource
from zebra_agent_worker.worker_mcp_catalog import prepare_worker_mcp

WorkerExtensionSnapshotStore = WorkerExtensionStore
WorkerSkillSource = worker_skills.WorkerSkillCatalogSource


class ExecutionComposition(Protocol):
    _settings: ZebraAgentSettings
    _model_http_client: httpx.Client | None
    _session_history: SessionHistoryPort
    _artifact_payload_store: ArtifactPayloadStorePort | None
    _egress_registry: HostConnectorRegistryPort | None
    _delegation_store: object | None
    _deployment_namespace: str | None
    _frozen_manifest_loader: Callable[[str], object] | None
    _client_runtime: Callable[[SessionId], ClientToolGateway | None] | None
    _extensions: "ExtensionRuntime"


class ModelGatewayBuilder(Protocol):
    def __call__(
        self, settings: ModelProviderSettings, *, client: httpx.Client | None = None
    ) -> ModelGatewayPort: ...


def model_gateway(service: ExecutionComposition, builder: ModelGatewayBuilder) -> ModelGatewayPort:
    settings = model_provider_settings(service._settings)
    if service._model_http_client is not None:
        return builder(settings, client=service._model_http_client)
    return builder(settings)


@dataclass(frozen=True, slots=True)
class ExtensionRuntime:
    snapshot_store: WorkerExtensionStore | None
    skills: worker_skills.WorkerSkillCatalogSource | None
    mcp: WorkerMcpSource | None = None


def extensions(
    extension_store: WorkerExtensionStore | None,
    skill_source: worker_skills.WorkerSkillCatalogSource | None,
    mcp_source: WorkerMcpSource | None = None,
) -> ExtensionRuntime:
    store, source = worker_skills.require_recovery(extension_store, skill_source)
    if mcp_source is not None and store is None:
        raise ValueError("MCP Worker requires extension snapshot recovery")
    return ExtensionRuntime(store, source, mcp_source)


def build_execution_tool_gateway(
    service: ExecutionComposition,
    *,
    task: RecoveredTask,
    model_gateway: ModelGatewayPort,
    session_id: SessionId,
    runtime: RuntimePort,
    runtime_handle: RuntimeHandle,
    cloud_artifacts: CloudToolOutputArtifactCoordinator | None,
    trusted_local: bool,
    task_binding: TaskBindingSnapshot | None,
    materialized_context: ContextMaterialization | None,
    extension: RecoveredTurnExtension | None,
    fence: LeaseFence,
) -> WorkerToolGateway:
    """Compose one execution gateway from already trusted Worker state."""
    gateway = build_worker_tool_gateway(
        task,
        settings=service._settings,
        model_gateway=model_gateway,
        session_history=service._session_history,
        session_id=session_id,
        runtime=runtime,
        runtime_handle=runtime_handle,
        local_artifacts=service._artifact_payload_store,
        cloud_artifacts=cloud_artifacts,
        trusted_local=trusted_local,
        egress_registry=service._egress_registry,
        delegation_store=service._delegation_store,
        parent_task_id=session_id,
        durable_delegation=service._settings.deployment == "cloud",
        parent_binding_digest=task_binding.binding_digest if task_binding else None,
        parent_binding=task_binding,
        parent_context=materialized_context,
        manifest_digest=(task_binding.host_capability.manifest_digest if task_binding else None),
        frozen_manifest_loader=service._frozen_manifest_loader,
        client_gateway=(service._client_runtime(session_id) if service._client_runtime else None),
        skill_catalog=worker_skills.prepare_worker_skill_catalog(
            extension,
            deployment_namespace=service._deployment_namespace or "",
            source=service._extensions.skills,
        ),
        skill_component_names=(
            tuple(item.version.skill_id for item in extension.snapshot.skills)
            if extension is not None
            else ()
        ),
        cloud_mcp_transport=prepare_worker_mcp(
            extension, source=service._extensions.mcp, session_id=session_id, fence=fence,
        ),
    )
    gateway.management = prepare_extension_management(
        extension, mcp=service._extensions.mcp, skills=service._extensions.skills,
        session_id=session_id, fence=fence,
        allow_network=task.network_profile.name.value in ("mcp-proxy-only", "full-trusted-local"),
    )
    if gateway.management is not None and extension is not None:
        context = extension.task_ceiling.binding.host_capability.host_context
        assert context is not None
        gateway.management_names = (
            (READ_NAMES if "extensions.read" in context.scopes else frozenset())
            | (WRITE_NAMES if "extensions.manage" in context.scopes else frozenset())
        )
        if gateway.management.refresh is None:
            gateway.management_names -= {"extensions.refresh_mcp"}
        if gateway.management.import_skill is None:
            gateway.management_names -= {"extensions.import_skill"}
    return gateway

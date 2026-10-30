"""Narrow tool-gateway composition extracted from the execution lifecycle."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports import (
    ArtifactPayloadReadPort,
    ArtifactPayloadStorePort,
    ModelGatewayPort,
    SessionHistoryPort,
)
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_integrations import ModelProviderSettings
from agent_integrations.bundle_model import BundleModelGateway
from agent_tools.extension_management import READ_NAMES, WRITE_NAMES
from zebra_agent_config import ZebraAgentSettings

import zebra_agent_worker.worker_skill_catalog as worker_skills
from zebra_agent_worker.client_tool_gateway import ClientToolGateway
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.extension_recovery import RecoveredTurnExtension, WorkerExtensionStore
from zebra_agent_worker.provider_configuration import model_provider_settings
from zebra_agent_worker.runtime_instances import BoundInstanceFactory
from zebra_agent_worker.task_recovery import RecoveredTask
from zebra_agent_worker.tool_gateway_runtime import WorkerToolGateway, build_worker_tool_gateway
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator
from zebra_agent_worker.worker_extension_management import prepare_extension_management
from zebra_agent_worker.worker_mcp_catalog import WorkerMcpSource as WorkerMcpSource
from zebra_agent_worker.worker_mcp_catalog import prepare_worker_mcp
from zebra_agent_worker.worker_plugins import WorkerPluginSource as WorkerPluginSource
from zebra_agent_worker.worker_plugins import prepare_worker_plugins

WorkerExtensionSnapshotStore = WorkerExtensionStore
WorkerSkillSource = worker_skills.WorkerSkillCatalogSource


class ExecutionComposition(Protocol):
    _event_store: EventStorePort
    _database_path: Path
    _settings: ZebraAgentSettings
    _model_http_client: httpx.Client | None
    _session_history: SessionHistoryPort
    _artifact_payload_store: ArtifactPayloadStorePort | None
    _artifact_payload_reader: ArtifactPayloadReadPort
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


def model_gateway(
    service: ExecutionComposition,
    builder: ModelGatewayBuilder,
    *,
    task: RecoveredTask | None = None,
) -> ModelGatewayPort:
    from zebra_agent_worker.bundle_assembly import task_assembly

    assembly = task_assembly(task) if task is not None else None
    if assembly is not None:
        return BundleModelGateway(assembly, client=service._model_http_client)
    settings = model_provider_settings(service._settings)
    if service._model_http_client is not None:
        return builder(settings, client=service._model_http_client)
    return builder(settings)


@dataclass(frozen=True, slots=True)
class ExtensionRuntime:
    snapshot_store: WorkerExtensionStore | None
    skills: worker_skills.WorkerSkillCatalogSource | None
    mcp: WorkerMcpSource | None = None
    plugins: WorkerPluginSource | None = None


def extensions(
    extension_store: WorkerExtensionStore | None,
    skill_source: worker_skills.WorkerSkillCatalogSource | None,
    mcp_source: WorkerMcpSource | None = None,
    plugin_source: WorkerPluginSource | None = None,
) -> ExtensionRuntime:
    store, source = worker_skills.require_recovery(extension_store, skill_source)
    if mcp_source is not None and store is None:
        raise ValueError("MCP Worker requires extension snapshot recovery")
    if plugin_source is not None and store is None:
        raise ValueError("plugin Worker requires extension snapshot recovery")
    return ExtensionRuntime(store, source, mcp_source, plugin_source)


def build_execution_tool_gateway(
    service: ExecutionComposition,
    *,
    task: RecoveredTask,
    model_gateway: ModelGatewayPort,
    session_id: SessionId,
    runtime: RuntimePort,
    runtime_handle: RuntimeHandle | None,
    cloud_artifacts: CloudToolOutputArtifactCoordinator | None,
    trusted_local: bool,
    task_binding: TaskBindingSnapshot | None,
    materialized_context: ContextMaterialization | None,
    extension: RecoveredTurnExtension | None,
    fence: LeaseFence,
    attempt_number: int = 1,
    network_cancellation_check: Callable[[], None] | None = None,
    script_recorder: Callable[[], DurableHarnessEventRecorder] | None = None,
    instance_factory: BoundInstanceFactory | None = None,
    binding_loader: Callable[[SessionId], object] | None = None,
) -> WorkerToolGateway:
    """Compose one execution gateway from already trusted Worker state."""
    plugin_guard = prepare_worker_plugins(
        extension,
        source=service._extensions.plugins,
        skills_available=service._extensions.skills is not None,
        mcp_available=service._extensions.mcp is not None,
    )
    skill_catalog = worker_skills.prepare_worker_skill_catalog(
        extension,
        deployment_namespace=service._deployment_namespace or "",
        source=service._extensions.skills,
        plugin_guard=plugin_guard,
    )
    gateway = build_worker_tool_gateway(
        task,
        settings=service._settings,
        model_gateway=model_gateway,
        session_history=service._session_history,
        session_id=session_id,
        runtime=runtime,
        runtime_handle=runtime_handle,
        local_artifacts=service._artifact_payload_store,
        artifact_payload_reader=getattr(service, "_artifact_payload_reader", None),
        cloud_artifacts=cloud_artifacts,
        trusted_local=trusted_local,
        egress_registry=service._egress_registry,
        delegation_store=service._delegation_store,
        parent_task_id=task_binding.task_id if task_binding else session_id,
        parent_attempt_number=attempt_number,
        durable_delegation=service._settings.deployment == "cloud",
        parent_binding_digest=task_binding.binding_digest if task_binding else None,
        parent_binding=task_binding,
        parent_context=materialized_context,
        network_cancellation_check=network_cancellation_check,
        manifest_digest=(task_binding.host_capability.manifest_digest if task_binding else None),
        frozen_manifest_loader=service._frozen_manifest_loader,
        client_gateway=(service._client_runtime(session_id) if service._client_runtime else None),
        skill_catalog=skill_catalog,
        skill_component_names=(
            tuple(item.version.skill_id for item in extension.snapshot.skills)
            if extension is not None
            else ()
        ),
        cloud_mcp_transport=prepare_worker_mcp(
            extension,
            source=service._extensions.mcp,
            session_id=session_id,
            fence=fence,
            plugin_guard=plugin_guard,
        ),
        resource_authority_issuer=(
            task_binding.host_capability.authority_issuer if task_binding is not None else None
        ),
    )
    gateway.management = prepare_extension_management(
        extension,
        mcp=service._extensions.mcp,
        skills=service._extensions.skills,
        session_id=session_id,
        fence=fence,
        skill_catalog=skill_catalog,
        plugin_guard=plugin_guard,
        allow_network=task.network_profile.name.value
        in ("mcp-proxy-only", "full-gateway", "full-trusted-local"),
    )
    if gateway.management is not None and extension is not None:
        context = extension.task_ceiling.binding.host_capability.host_context
        assert context is not None
        gateway.management_names = (
            READ_NAMES if "extensions.read" in context.scopes else frozenset()
        ) | (WRITE_NAMES if "extensions.manage" in context.scopes else frozenset())
        if gateway.management.refresh is None:
            gateway.management_names -= {"extensions.refresh_mcp"}
        if gateway.management.import_skill is None:
            gateway.management_names -= {"extensions.import_skill"}
    if script_recorder is not None:
        from zebra_agent_worker.native_scripts import prepare_native_scripts

        scripts = prepare_native_scripts(
            settings=service._settings,
            database_path=service._database_path,
            task=task,
            binding=task_binding,
            events=service._event_store,
            recorder=script_recorder,
            instance_factory=instance_factory,
            attempt_number=attempt_number,
            binding_loader=binding_loader,
        )
        if scripts is not None:
            if scripts.names & {tool.name for tool in gateway.model_tools}:
                raise ValueError("native script tool name conflicts with an existing capability")
            gateway.native_scripts = scripts
    return gateway

from dataclasses import dataclass

from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.artifact_payload_read import ArtifactPayloadReadPort
from agent_core.ports.cloud_artifact_payload_store import CloudArtifactPayloadStorePort
from agent_core.ports.context_lifecycle_store import ContextLifecycleStorePort
from agent_core.ports.context_materialization import ContextMaterializationPort
from agent_core.ports.delivery_audit_store import DeliveryAuditStorePort
from agent_core.ports.effect_dispatch import EffectDispatchPort
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.governed_memory_store import GovernedMemoryStorePort
from agent_core.ports.handoff_dispatch_store import HandoffDispatchStorePort
from agent_core.ports.idempotency_store import IdempotencyStorePort
from agent_core.ports.lease_store import LeaseStorePort
from agent_core.ports.model_tool_projection import ModelToolProjectionPort
from agent_core.ports.projection_store import ProjectionStorePort
from agent_core.ports.provider_continuation_cloud import CloudProviderContinuationStorePort
from agent_core.ports.session_artifact_read import SessionArtifactReadPort
from agent_core.ports.session_handoff import SessionHandoffPort
from agent_core.ports.session_history import SessionHistoryPort
from agent_core.ports.workspace_projection_store import WorkspaceProjectionStorePort


@dataclass(frozen=True, slots=True)
class CloudControlPlane:
    """Cloud-only storage contract; local ``ControlPlaneStores`` is unchanged."""

    deployment_namespace: str
    events: EventStorePort
    sessions: ProjectionStorePort
    workspaces: WorkspaceProjectionStorePort
    tasks: AgentTaskPort
    leases: LeaseStorePort
    context_lifecycle: ContextLifecycleStorePort
    context_materialization: ContextMaterializationPort
    handoffs: SessionHandoffPort
    handoff_dispatch: HandoffDispatchStorePort
    idempotency: IdempotencyStorePort
    effects: EffectDispatchPort
    memories: GovernedMemoryStorePort
    artifact_payloads: CloudArtifactPayloadStorePort
    artifact_payload_reader: ArtifactPayloadReadPort
    model_tool_projections: ModelToolProjectionPort
    artifacts: SessionArtifactReadPort
    provider_continuations: CloudProviderContinuationStorePort
    session_history: SessionHistoryPort
    delivery_audit: DeliveryAuditStorePort

    def __post_init__(self) -> None:
        namespace = self.deployment_namespace
        if (
            not isinstance(namespace, str)
            or not namespace
            or namespace != namespace.strip()
            or len(namespace) > 255
        ):
            raise ValueError("cloud control-plane namespace must be trimmed and <= 255 chars")

"""Hexagonal ports for Zebra Agent core."""

from agent_core.domain.leases import (
    LeaseCheckpointRegressionError,
    LeaseConflictError,
    LeaseFence,
    LeaseLostError,
)
from agent_core.domain.memory_delivery import MemoryDeliveryCertainty
from agent_core.ports.agent_memory_gateway import (
    AgentMemoryGatewayPort,
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewayHit,
    MemoryGatewayMutationCertainty,
    MemoryGatewayMutationResult,
    MemoryGatewaySearchRequest,
    MemoryGatewaySearchResult,
    MemoryGatewayStatus,
)
from agent_core.ports.agent_registry import AgentRegistryPort
from agent_core.ports.agent_tasks import AgentTaskPort, FencedAgentTaskStorePort, TaskEvent
from agent_core.ports.aggregate_mutation import (
    AdministrativeMutationCAS,
    WorkerMutationAuthority,
)
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_core.ports.artifact_payload_read import (
    ArtifactPayloadObjectReadPort,
    ArtifactPayloadReadInspection,
    ArtifactPayloadReadPort,
    ArtifactPayloadReadPrunedError,
    ArtifactPayloadReadStatus,
    ArtifactPayloadReadUnavailableError,
)
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.artifact_store import ArtifactStorePort
from agent_core.ports.clock import ClockPort
from agent_core.ports.cloud_artifact_payload_store import CloudArtifactPayloadStorePort
from agent_core.ports.cloud_control_plane import CloudControlPlane
from agent_core.ports.committed_event_publisher import CommittedEventPublisherPort
from agent_core.ports.context_compiler import ContextCompilerPort, RuntimeEvidenceInput
from agent_core.ports.context_lifecycle_store import (
    ContextLifecycleCommitResult,
    ContextLifecycleStorePort,
    StoredContextCapsule,
)
from agent_core.ports.context_materialization import ContextMaterializationPort
from agent_core.ports.conversation_compactor import (
    ConversationCompactionResult,
    ConversationCompactorPort,
)
from agent_core.ports.delivery_audit_store import DeliveryAuditStorePort
from agent_core.ports.delivery_transaction import (
    DeliveryClaimResult,
    DeliveryClaimResultType,
    DeliveryCommitResult,
    DeliveryCommitResultType,
    DeliveryReplayResult,
    DeliveryReplayResultType,
    DeliveryTransactionPort,
)
from agent_core.ports.effect_dispatch import EffectDispatchPort
from agent_core.ports.effect_ledger import (
    EffectLedgerPort,
    EffectLedgerStatus,
    EffectReservation,
)
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.governed_memory_store import (
    GovernedMemoryScanCursor,
    GovernedMemoryScanPage,
    GovernedMemoryScanQuery,
    GovernedMemoryStorePort,
)
from agent_core.ports.handoff_dispatch_store import (
    FencedHandoffDispatchStorePort,
    HandoffDispatch,
    HandoffDispatchStorePort,
)
from agent_core.ports.idempotency_store import IdempotencyRecord, IdempotencyStorePort
from agent_core.ports.lease_store import LeaseStorePort
from agent_core.ports.live_event_fanout import (
    LiveEventBatch,
    LiveEventCursor,
    LiveEventEnvelope,
    LiveEventFanoutPort,
)
from agent_core.ports.memory_delivery import MemoryDeliveryLedgerPort
from agent_core.ports.memory_store import MemoryStorePort
from agent_core.ports.model_call_store import ModelCallStorePort
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.model_tool_projection import ModelToolProjectionPort
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_core.ports.projection_store import ProjectionStorePort
from agent_core.ports.provider_continuation import ProviderContinuationPort
from agent_core.ports.provider_continuation_cloud import (
    CloudProviderContinuationCommitResult,
    CloudProviderContinuationStorePort,
    LoadedCloudProviderContinuation,
    ProviderContinuationSweepReceipt,
)
from agent_core.ports.provider_continuation_store import (
    LoadedProviderContinuation,
    ProviderContinuationStorePort,
)
from agent_core.ports.runtime import (
    EffectiveRuntimeAuthority,
    RuntimeCapabilities,
    RuntimeCapabilityError,
    RuntimeClass,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
    RuntimeHandle,
    RuntimeLimits,
    RuntimePort,
    RuntimeSnapshot,
    RuntimeSnapshotCleanupResult,
    RuntimeSnapshotInspection,
    RuntimeSnapshotStatus,
    SandboxSpec,
)
from agent_core.ports.session_artifact_read import (
    PreviewState,
    SessionArtifact,
    SessionArtifactReadPort,
)
from agent_core.ports.session_handoff import (
    HandoffOperation,
    HandoffSourceFacts,
    SessionHandoffAbortPort,
    SessionHandoffAbortRequest,
    SessionHandoffCommitRequest,
    SessionHandoffCreateRequest,
    SessionHandoffPort,
    SessionHandoffResult,
)
from agent_core.ports.session_history import SessionHistoryPort
from agent_core.ports.subagents import SubagentPort
from agent_core.ports.tool_gateway import ToolGatewayPort
from agent_core.ports.tool_run_store import ToolRunStorePort
from agent_core.ports.workspace import WorkspacePort
from agent_core.ports.workspace_projection_store import (
    WorkerProjectionCommitResult,
    WorkerProjectionTransactionPort,
    WorkspaceProjectionStorePort,
)

__all__ = [
    "AgentMemoryGatewayPort",
    "AgentRegistryPort",
    "AdministrativeMutationCAS",
    "ArtifactPayloadStorePort",
    "ArtifactPayloadReadInspection",
    "ArtifactPayloadObjectReadPort",
    "ArtifactPayloadReadPort",
    "ArtifactPayloadReadPrunedError",
    "ArtifactPayloadReadStatus",
    "ArtifactPayloadReadUnavailableError",
    "ArtifactObjectStorePort",
    "AgentTaskPort",
    "FencedAgentTaskStorePort",
    "ArtifactStorePort",
    "ClockPort",
    "CloudArtifactPayloadStorePort",
    "ContextCompilerPort",
    "ContextMaterializationPort",
    "CloudControlPlane",
    "CommittedEventPublisherPort",
    "ContextLifecycleCommitResult",
    "ContextLifecycleStorePort",
    "ConversationCompactionResult",
    "ConversationCompactorPort",
    "DeliveryAuditStorePort",
    "DeliveryClaimResult",
    "DeliveryClaimResultType",
    "DeliveryCommitResult",
    "DeliveryCommitResultType",
    "DeliveryReplayResult",
    "DeliveryReplayResultType",
    "DeliveryTransactionPort",
    "EffectDispatchPort",
    "EffectLedgerPort",
    "EffectLedgerStatus",
    "EffectReservation",
    "EventStorePort",
    "EffectiveRuntimeAuthority",
    "HandoffDispatch",
    "HandoffDispatchStorePort",
    "FencedHandoffDispatchStorePort",
    "HandoffSourceFacts",
    "SessionHandoffAbortPort",
    "SessionHandoffAbortRequest",
    "GovernedMemoryStorePort",
    "GovernedMemoryScanCursor",
    "GovernedMemoryScanPage",
    "GovernedMemoryScanQuery",
    "IdempotencyRecord",
    "IdempotencyStorePort",
    "LeaseStorePort",
    "LeaseCheckpointRegressionError",
    "LeaseConflictError",
    "LeaseFence",
    "LeaseLostError",
    "LiveEventBatch",
    "LiveEventCursor",
    "LiveEventEnvelope",
    "LiveEventFanoutPort",
    "MemoryStorePort",
    "MemoryDeliveryLedgerPort",
    "ConfirmedMemoryPublication",
    "MemoryGatewayDeleteRequest",
    "MemoryGatewayHit",
    "MemoryGatewayMutationResult",
    "MemoryGatewayMutationCertainty",
    "MemoryDeliveryCertainty",
    "MemoryGatewaySearchRequest",
    "MemoryGatewaySearchResult",
    "MemoryGatewayStatus",
    "ModelCallStorePort",
    "ModelToolProjectionPort",
    "ModelGatewayPort",
    "LoadedProviderContinuation",
    "PreviewState",
    "ProviderContinuationPort",
    "CloudProviderContinuationCommitResult",
    "CloudProviderContinuationStorePort",
    "LoadedCloudProviderContinuation",
    "ProviderContinuationSweepReceipt",
    "ProviderContinuationStorePort",
    "PolicyEnginePort",
    "ProjectionStorePort",
    "RuntimeCapabilityError",
    "RuntimeCapabilities",
    "RuntimeClass",
    "RuntimeExecutionRequest",
    "RuntimeExecutionResult",
    "RuntimeEvidenceInput",
    "RuntimeHandle",
    "RuntimeLimits",
    "RuntimePort",
    "RuntimeSnapshot",
    "RuntimeSnapshotCleanupResult",
    "RuntimeSnapshotInspection",
    "RuntimeSnapshotStatus",
    "SandboxSpec",
    "SessionHistoryPort",
    "SessionArtifact",
    "SessionArtifactReadPort",
    "HandoffOperation",
    "SessionHandoffCommitRequest",
    "SessionHandoffCreateRequest",
    "SessionHandoffPort",
    "SessionHandoffResult",
    "SubagentPort",
    "StoredContextCapsule",
    "ToolGatewayPort",
    "ToolRunStorePort",
    "TaskEvent",
    "WorkspaceProjectionStorePort",
    "WorkspacePort",
    "WorkerMutationAuthority",
    "WorkerProjectionCommitResult",
    "WorkerProjectionTransactionPort",
]

"""Hexagonal ports for Zebra Agent core."""

from agent_core.domain.leases import (
    LeaseCheckpointRegressionError,
    LeaseConflictError,
    LeaseFence,
    LeaseLostError,
)
from agent_core.ports.agent_memory_gateway import (
    AgentMemoryGatewayPort,
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewayHit,
    MemoryGatewayMutationResult,
    MemoryGatewaySearchRequest,
    MemoryGatewaySearchResult,
    MemoryGatewayStatus,
)
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEvent
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.artifact_store import ArtifactStorePort
from agent_core.ports.clock import ClockPort
from agent_core.ports.context_compiler import ContextCompilerPort, RuntimeEvidenceInput
from agent_core.ports.context_lifecycle_store import (
    ContextLifecycleStorePort,
    StoredContextCapsule,
)
from agent_core.ports.conversation_compactor import (
    ConversationCompactionResult,
    ConversationCompactorPort,
)
from agent_core.ports.delivery_audit_store import DeliveryAuditStorePort
from agent_core.ports.effect_dispatch import EffectDispatchPort
from agent_core.ports.effect_ledger import (
    EffectLedgerPort,
    EffectLedgerStatus,
    EffectReservation,
)
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.handoff_dispatch_store import (
    HandoffDispatch,
    HandoffDispatchStorePort,
)
from agent_core.ports.idempotency_store import IdempotencyRecord, IdempotencyStorePort
from agent_core.ports.lease_store import LeaseStorePort
from agent_core.ports.memory_store import MemoryStorePort
from agent_core.ports.model_call_store import ModelCallStorePort
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_core.ports.projection_store import ProjectionStorePort
from agent_core.ports.provider_continuation import ProviderContinuationPort
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
from agent_core.ports.workspace_projection_store import WorkspaceProjectionStorePort

__all__ = [
    "AgentMemoryGatewayPort",
    "ArtifactPayloadStorePort",
    "AgentTaskPort",
    "ArtifactStorePort",
    "ClockPort",
    "ContextCompilerPort",
    "ContextLifecycleStorePort",
    "ConversationCompactionResult",
    "ConversationCompactorPort",
    "DeliveryAuditStorePort",
    "EffectDispatchPort",
    "EffectLedgerPort",
    "EffectLedgerStatus",
    "EffectReservation",
    "EventStorePort",
    "EffectiveRuntimeAuthority",
    "HandoffDispatch",
    "HandoffDispatchStorePort",
    "HandoffSourceFacts",
    "IdempotencyRecord",
    "IdempotencyStorePort",
    "LeaseStorePort",
    "LeaseCheckpointRegressionError",
    "LeaseConflictError",
    "LeaseFence",
    "LeaseLostError",
    "MemoryStorePort",
    "ConfirmedMemoryPublication",
    "MemoryGatewayDeleteRequest",
    "MemoryGatewayHit",
    "MemoryGatewayMutationResult",
    "MemoryGatewaySearchRequest",
    "MemoryGatewaySearchResult",
    "MemoryGatewayStatus",
    "ModelCallStorePort",
    "ModelGatewayPort",
    "LoadedProviderContinuation",
    "PreviewState",
    "ProviderContinuationPort",
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
]

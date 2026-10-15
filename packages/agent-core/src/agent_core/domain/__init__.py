"""Public exports load on demand; direct submodule imports stay bounded."""

# ruff: noqa: F405 -- TYPE_CHECKING exports and __getattr__ define the public names.

from importlib import import_module as _import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._public_exports import *  # noqa: F403

__all__ = [
    "ArtifactRetentionPolicy", "ArtifactRetentionProfile", "ArtifactAccessClass",
    "ArtifactAccessDescriptor", "ArtifactPayloadInspection",
    "ArtifactPayloadLifecycleStatus", "ArtifactPayloadStatus", "ArtifactPayloadWrite",
    "ArtifactObjectConflictError", "ArtifactObjectCleanupEvidence",
    "ArtifactObjectDeleteRequest", "ArtifactObjectDeleteResult",
    "ArtifactObjectDeleteStatus", "ArtifactObjectExpectation",
    "ArtifactObjectIntegrityError", "ArtifactObjectNotFoundError",
    "ArtifactObjectPutRequest", "ArtifactObjectReceipt",
    "ArtifactObjectUnavailableError", "ArtifactObjectVerification",
    "ArtifactObjectVerificationStatus", "ArtifactBeginPruneRequest",
    "ArtifactCompensateRequest", "ArtifactCompletePruneRequest", "ArtifactEventBinding",
    "ArtifactFinalizeRequest", "ArtifactManagementContext", "ArtifactMetadataQuery",
    "ArtifactReconcileQuery", "ArtifactRecordObjectRequest", "ArtifactReserveRequest",
    "canonical_artifact_reserve_hash", "ArtifactRef", "OpaqueAuthorityScope",
    "HostAuthorityError", "HostContextEnvelope", "Capability", "GrantScope",
    "HostCapabilityManifestV1", "HostConnectorBinding", "HostConnectorProfileVersion",
    "HostConnectorStatus", "AgentCapabilityCeilingSnapshot", "HostCapabilitySnapshot",
    "TaskBindingSnapshot", "accepts_new_tasks", "fails_closed_for_running_tasks",
    "DailyScheduleTrigger", "IntervalScheduleTrigger", "OnceScheduleTrigger",
    "ScheduleAuthorityBinding", "ScheduleFiringStatus", "ScheduleMisfirePolicy",
    "ScheduleOverlapPolicy", "ScheduleOwner", "ScheduleTrigger",
    "ScheduledTaskTemplate", "SCHEDULE_FIRING_TERMINAL_STATUSES", "TaskSchedule",
    "TaskScheduleFiring", "TaskScheduleStatus", "WeeklyScheduleTrigger",
    "HostEffectReceipt", "HostEffectStatus", "HostToolContractV1",
    "ResourceBindingRule", "capability", "capability_set", "grant_scope",
    "grant_scope_set", "intersect_capabilities", "bind_task",
    "compute_effective_capabilities", "uncertain_receipt", "HostGrantExpiredError",
    "HostGrantMismatchError", "HostGrantNotYetValidError", "HostGrantScopeError",
    "HostResourceRef", "HostSessionGrant", "HostTechnicalLimits",
    "ContextMaterialization", "ContextMaterializationGeneration",
    "ContextMaterializationMode", "ContextMaterializationRequest",
    "ContextInheritanceMode", "DelegatedContextItem", "DelegatedContextSnapshot",
    "MAX_DELEGATED_CONTEXT_CHARS", "MAX_DELEGATED_CONTEXT_ITEM_CHARS",
    "MAX_DELEGATED_CONTEXT_ITEMS", "REQUIRED_CONTEXT_OMISSIONS",
    "MAX_CONTEXT_HISTORY_MESSAGES", "MAX_CONTEXT_MEMORY_ENTRIES", "AgentTask",
    "AgentDefinition", "AgentDefinitionScope", "AgentDefinitionVersion", "AgentRelease",
    "AgentReleaseStatus", "AgentReleaseTransitionError", "AgentDefinitionDraft",
    "AgentDefinitionDraftValidation", "AgentDraftValidationIssue",
    "AgentDraftValidationStatus", "canonical_agent_definition_digest",
    "AttachmentContextInput", "ImageAttachmentContextInput", "ImageAttachmentInput",
    "SUPPORTED_IMAGE_MEDIA_TYPES", "DeliveryAuditRecord", "DeliveryTransactionConflictError",
    "DeliveryTransactionInvariantError", "DeliveryTransactionNotFoundError",
    "DeliveryTransactionOwnershipError", "DeliveryTransactionRecord",
    "DeliveryTransactionState", "DeliveryTransactionStateError",
    "validate_delivery_transaction_transition", "ClarificationContext",
    "ContextLifecycleController", "ContextLifecycleDecision", "ContextLifecycleSignals",
    "CloudArtifactPayloadConflictError", "CloudArtifactPayloadLifecycleStatus",
    "CloudArtifactPayloadNotFoundError", "CloudArtifactPayloadRecord",
    "CloudArtifactPayloadStateError", "EventActor", "EventType",
    "AdministrativeMemoryReviewRequest", "GovernedMemoryCommitResult",
    "GovernedMemoryConflictError", "GovernedMemoryCreate", "GovernedMemoryEntry",
    "GovernedMemoryLifecycleMutation", "GovernedMemoryManagementContext",
    "GovernedMemoryOperationKind", "GovernedMemoryOperationReceipt",
    "GovernedMemoryReviewAction", "GovernedMemoryRevision", "GovernedMemoryStateError",
    "GovernedMemoryTombstone", "WorkerMemoryMutationPlan",
    "canonical_administrative_memory_review_hash",
    "canonical_governed_memory_content_hash", "canonical_governed_memory_creation_key",
    "canonical_governed_memory_result_hash", "canonical_worker_memory_mutation_hash",
    "EffectClaim", "EffectDispatch", "EffectDispatchConflictError",
    "EffectDispatchStateError", "EffectDispatchStatus", "EffectEvidence",
    "ExecutionSegment", "EffectIdentity", "EffectResolutionOutcome",
    "EffectScheduleRequest", "CompletedToolEvidence", "HandoffActorKind",
    "HandoffOperationStatus", "HandoffReason", "HandoffSideEffectClass", "MessageRole",
    "MemoryQuery", "MemoryRecord", "MemoryStatus", "MemoryType", "MemoryVisibility",
    "MemoryDeliveryCertainty", "MemoryDeliveryOperation",
    "MemoryDeliveryOperationRecord", "MemoryDeliveryScope", "MemoryDeliveryScopeState",
    "MemoryDeliveryState", "MemoryDeliveryTransition",
    "validate_memory_delivery_transition", "LeaseCheckpointRegressionError",
    "LeaseConflictError", "DEFAULT_MAX_LEASE_TTL", "LeaseFence", "LeaseLostError",
    "ModelCallRecord", "PolicyDecision", "PolicyDecisionType", "PlanStep",
    "PlanStepStatus", "Session", "SessionHandoffEnvelope",
    "SessionHandoffValidationContext", "SessionHandoffValidationError",
    "SessionLineage", "SessionEvent", "SessionMessage", "SessionStatus",
    "RolloverReason", "SegmentVisibility", "SessionPlan", "StoredArtifactPayload",
    "SessionAttachmentRef", "TextAttachmentInput", "ToolCall", "ToolCallStatus",
    "ToolExecutionLocation", "ToolIdempotency", "ToolReceipt", "ToolProfile",
    "ToolRunRecord", "ToolResult", "ToolRisk", "WorkerLease", "WorkspaceAction",
    "WorkspaceId", "WorkspaceInstance", "WorkspaceLifecycleState", "WorkspaceSource",
    "WorkspaceSourceKind", "WorkspaceTransitionError", "next_workspace_state",
    "WorkspaceProjection", "WorkspaceBindingRevision", "WorkspaceStatus",
    "ClientActionContract", "ClientActionRisk", "ClientCapabilityError",
    "ClientComponentContract", "ClientReadableContract",
    "FrontendCapabilityProfileVersion", "MountedCapabilitySnapshot", "ProfileLifecycle",
    "CLIENT_EFFECT_TERMINAL_STATUSES", "ClientEffectContinuation",
    "ClientEffectReceipt", "ClientEffectRequest", "ClientEffectStatus",
    "ClientRunBinding", "client_run_binding_key", "ClientControlFence",
    "ClientControlLease", "ClientSession", "ClientSessionGrant", "ClientSessionStatus",
    "validate_session_handoff",
]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # ponytail: first public access loads the original aggregate; per-name lazy
    # exports are only needed if aggregate consumers also need lower startup cost.
    value = getattr(_import_module(f"{__name__}._public_exports"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

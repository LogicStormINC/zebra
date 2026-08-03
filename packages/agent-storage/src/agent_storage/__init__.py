"""Storage adapters for Zebra Agent."""

from agent_core.domain.leases import (
    LeaseCheckpointRegressionError,
    LeaseConflictError,
    LeaseFence,
    LeaseLostError,
)
from agent_core.ports import (
    EffectLedgerStatus,
    EffectReservation,
    HandoffDispatch,
    HandoffSourceFacts,
    IdempotencyRecord,
    LoadedProviderContinuation,
    SessionArtifact,
    StoredContextCapsule,
)

from agent_storage.agent_tasks import SQLiteAgentTaskStore
from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.artifact_payload_reads import (
    CloudArtifactPayloadReader,
    LocalArtifactPayloadReader,
)
from agent_storage.artifact_payloads import (
    ArtifactPayloadMissingError,
    SQLiteArtifactPayloadStore,
)
from agent_storage.artifact_projection import (
    artifact_id_from_uri,
    payload_for_artifact_uri,
    serialize_artifact_lifecycle,
    serialize_artifact_retrieval,
    serialize_session_artifact_projection,
)
from agent_storage.artifacts import SQLiteArtifactStore, compose_session_artifacts
from agent_storage.composition import (
    ControlPlaneStores,
    sqlite_control_plane_stores,
)
from agent_storage.context_lifecycle import (
    ActiveContextProjectionConflictError,
    ImmutableContextCapsuleConflictError,
    SQLiteContextLifecycleStore,
)
from agent_storage.delivery_audit import SQLiteDeliveryAuditStore
from agent_storage.effect_ledger import (
    EffectReplayRejectedError,
    SQLiteEffectLedger,
)
from agent_storage.event_rows import SessionEventIdempotencyConflictError
from agent_storage.idempotency import (
    IdempotencyConflictError,
    SQLiteIdempotencyStore,
    new_idempotency_record,
)
from agent_storage.leases import SQLiteLeaseStore
from agent_storage.memories import SQLiteMemoryStore
from agent_storage.memory_lookup import (
    list_confirmed_repo_memories,
    list_confirmed_repo_memory_texts,
)
from agent_storage.model_calls import SQLiteModelCallStore
from agent_storage.postgres import (
    GovernedMemoryImportError,
    GovernedMemoryImportQuarantine,
    GovernedMemoryImportReport,
    MemoryDeliveryClaim,
    MemoryDeliveryConflictError,
    MemoryDeliverySearchAdmission,
    MemoryProviderMapping,
    NativeMemoryConflictError,
    NativeMemoryError,
    NativeMemoryMutation,
    NativeMemoryNamespaceError,
    NativeMemoryOperation,
    NativeMemoryRecallHit,
    NativeMemoryReset,
    NativeMemoryStaleGenerationError,
    PostgresAgentTaskConflictError,
    PostgresAgentTaskStore,
    PostgresCloudArtifactPayloadStore,
    PostgresContextLifecycleConflictError,
    PostgresContextLifecycleStore,
    PostgresContextMaterializationConflictError,
    PostgresContextMaterializationStore,
    PostgresControlPlaneEpochError,
    PostgresDeliveryAuditStore,
    PostgresEffectDispatchStore,
    PostgresEventStore,
    PostgresGovernedMemoryStore,
    PostgresHandoffDispatchStore,
    PostgresIdempotencyStore,
    PostgresLeaseStore,
    PostgresMemoryDeliveryLedger,
    PostgresMemoryDeliveryStore,
    PostgresMigrationError,
    PostgresModelToolProjectionConflictError,
    PostgresModelToolProjectionStore,
    PostgresNativeMemoryGateway,
    PostgresProjectionConflictError,
    PostgresProjectionStore,
    PostgresProviderContinuationConflictError,
    PostgresProviderContinuationStore,
    PostgresSessionArtifactReadStore,
    PostgresSessionHandoffStore,
    PostgresSessionHistory,
    PostgresWorkspaceProjectionConflictError,
    PostgresWorkspaceProjectionStore,
    apply_postgres_migrations,
    attach_segment_in_transaction,
    bootstrap_control_plane_epoch,
    import_sqlite_governed_memories,
    read_control_plane_epoch,
    rebuild_task_in_transaction,
    rotate_control_plane_epoch,
)
from agent_storage.postgres_composition import (
    PostgresControlPlaneStores,
    postgres_control_plane_stores,
)
from agent_storage.projections import SQLiteProjectionStore
from agent_storage.provider_continuations import SQLiteProviderContinuationStore
from agent_storage.session_attachments import (
    load_attachment_contexts,
    store_initial_text_attachments,
    store_text_attachments,
)
from agent_storage.session_handoff_dispatch import SQLiteHandoffDispatchStore
from agent_storage.session_handoff_rows import (
    HandoffIdempotencyConflictError,
    HandoffStorageConflictError,
)
from agent_storage.session_handoffs import SQLiteSessionHandoffStore
from agent_storage.session_history import SQLiteSessionHistory
from agent_storage.skills_state import SkillStateRecord, SQLiteSkillsStateStore
from agent_storage.sqlite import SQLiteEventStore
from agent_storage.tool_runs import SQLiteToolRunStore
from agent_storage.workspaces import SQLiteWorkspaceProjectionStore

__all__ = [
    "ArtifactPayloadMissingError",
    "CloudArtifactPayloadReader",
    "S3ArtifactObjectStore",
    "ControlPlaneStores",
    "PostgresControlPlaneStores",
    "EffectLedgerStatus",
    "EffectReplayRejectedError",
    "EffectReservation",
    "ActiveContextProjectionConflictError",
    "IdempotencyConflictError",
    "IdempotencyRecord",
    "HandoffDispatch",
    "HandoffIdempotencyConflictError",
    "HandoffStorageConflictError",
    "HandoffSourceFacts",
    "ImmutableContextCapsuleConflictError",
    "LeaseConflictError",
    "LeaseCheckpointRegressionError",
    "LeaseFence",
    "LeaseLostError",
    "SessionArtifact",
    "SessionEventIdempotencyConflictError",
    "LoadedProviderContinuation",
    "list_confirmed_repo_memories",
    "artifact_id_from_uri",
    "SQLiteMemoryStore",
    "LocalArtifactPayloadReader",
    "list_confirmed_repo_memory_texts",
    "load_attachment_contexts",
    "payload_for_artifact_uri",
    "PostgresAgentTaskConflictError",
    "PostgresAgentTaskStore",
    "PostgresCloudArtifactPayloadStore",
    "PostgresEventStore",
    "PostgresHandoffDispatchStore",
    "PostgresIdempotencyStore",
    "PostgresGovernedMemoryStore",
    "GovernedMemoryImportError",
    "GovernedMemoryImportQuarantine",
    "GovernedMemoryImportReport",
    "import_sqlite_governed_memories",
    "PostgresSessionHandoffStore",
    "PostgresSessionHistory",
    "PostgresEffectDispatchStore",
    "PostgresControlPlaneEpochError",
    "PostgresContextLifecycleConflictError",
    "PostgresContextLifecycleStore",
    "PostgresContextMaterializationConflictError",
    "PostgresContextMaterializationStore",
    "PostgresDeliveryAuditStore",
    "PostgresLeaseStore",
    "PostgresMemoryDeliveryLedger",
    "PostgresMemoryDeliveryStore",
    "MemoryDeliveryClaim",
    "MemoryDeliveryConflictError",
    "MemoryDeliverySearchAdmission",
    "MemoryProviderMapping",
    "NativeMemoryConflictError",
    "NativeMemoryError",
    "NativeMemoryMutation",
    "NativeMemoryNamespaceError",
    "NativeMemoryOperation",
    "NativeMemoryRecallHit",
    "NativeMemoryReset",
    "NativeMemoryStaleGenerationError",
    "PostgresNativeMemoryGateway",
    "PostgresModelToolProjectionConflictError",
    "PostgresModelToolProjectionStore",
    "PostgresMigrationError",
    "PostgresProjectionConflictError",
    "PostgresProjectionStore",
    "PostgresProviderContinuationConflictError",
    "PostgresProviderContinuationStore",
    "PostgresSessionArtifactReadStore",
    "PostgresWorkspaceProjectionConflictError",
    "PostgresWorkspaceProjectionStore",
    "serialize_artifact_lifecycle",
    "serialize_artifact_retrieval",
    "serialize_session_artifact_projection",
    "compose_session_artifacts",
    "sqlite_control_plane_stores",
    "postgres_control_plane_stores",
    "apply_postgres_migrations",
    "attach_segment_in_transaction",
    "bootstrap_control_plane_epoch",
    "read_control_plane_epoch",
    "rotate_control_plane_epoch",
    "rebuild_task_in_transaction",
    "SQLiteArtifactPayloadStore",
    "SQLiteAgentTaskStore",
    "SQLiteArtifactStore",
    "SQLiteContextLifecycleStore",
    "SQLiteDeliveryAuditStore",
    "SQLiteEffectLedger",
    "SQLiteEventStore",
    "SQLiteIdempotencyStore",
    "SQLiteLeaseStore",
    "SQLiteModelCallStore",
    "SQLiteProjectionStore",
    "SQLiteProviderContinuationStore",
    "SQLiteSessionHistory",
    "SQLiteSkillsStateStore",
    "SQLiteHandoffDispatchStore",
    "SQLiteSessionHandoffStore",
    "SQLiteToolRunStore",
    "SQLiteWorkspaceProjectionStore",
    "SkillStateRecord",
    "StoredContextCapsule",
    "store_text_attachments",
    "store_initial_text_attachments",
    "new_idempotency_record",
]

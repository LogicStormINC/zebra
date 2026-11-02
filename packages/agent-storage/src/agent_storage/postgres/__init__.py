"""Public identities stay stable; narrow readers avoid full application bootstrap."""

# ruff: noqa: F405 -- TYPE_CHECKING exports define public types.
from importlib import import_module as _import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._public_exports import *  # noqa: F403
__all__ = [
    "FencedAgentTaskStorePort",
    "PostgresAgentTaskConflictError",
    "PostgresAgentTaskStore",
    "PostgresCloudArtifactPayloadStore",
    "PostgresSessionArtifactReadStore",
    "PostgresEventStore",
    "PostgresHandoffDispatchStore",
    "PostgresSessionHandoffStore",
    "PostgresSessionHistory",
    "PostgresTaskScheduleFiringStore",
    "PostgresTaskScheduleStore",
    "TaskScheduleStorageIntegrityError",
    "PostgresEffectDispatchStore",
    "PostgresControlPlaneEpochError",
    "PostgresContextLifecycleConflictError",
    "PostgresContextLifecycleStore",
    "PostgresContextMaterializationConflictError",
    "PostgresContextMaterializationStore",
    "PostgresDeliveryAuditStore",
    "PostgresDeliveryTransactionStore",
    "PostgresLeaseStore",
    "PostgresGovernedMemoryStore",
    "PostgresIdempotencyStore",
    "HostAuthorityStorageError",
    "HostGrantAuditRecord",
    "HostGrantAttempt",
    "HostGrantReplayDecision",
    "HostRegistryBindingError",
    "HostRegistryRecord",
    "PostgresHostAuthorityStore",
    "PostgresWorkspaceControlStore",
    "PostgresAgentRegistry",
    "AgentRegistryStorageError",
    "AgentDefinitionEvalEvidence",
    "PostgresMemoryDeliveryLedger",
    "PostgresMemoryDeliveryStore",
    "NativeMemoryConflictError",
    "NativeMemoryError",
    "NativeMemoryMutation",
    "NativeMemoryNamespaceError",
    "NativeMemoryOperation",
    "NativeMemoryRecallHit",
    "NativeMemoryReset",
    "NativeMemoryStaleGenerationError",
    "PostgresNativeMemoryGateway",
    "MemoryDeliveryClaim",
    "MemoryDeliveryConflictError",
    "MemoryDeliverySearchAdmission",
    "MemoryProviderMapping",
    "GovernedMemoryImportError",
    "GovernedMemoryImportQuarantine",
    "GovernedMemoryImportReport",
    "import_sqlite_governed_memories",
    "PostgresModelToolProjectionConflictError",
    "PostgresModelToolProjectionStore",
    "PostgresMigrationError",
    "PostgresProjectionConflictError",
    "PostgresProjectionStore",
    "PostgresWorkspaceProjectionConflictError",
    "PostgresWorkspaceProjectionStore",
    "PostgresProviderContinuationConflictError",
    "PostgresProviderContinuationStore",
    "PostgresUserPersonalizationStore",
    "apply_postgres_migrations",
    "CutoverConflictError",
    "DeliveryAuditMigrationError",
    "DeliveryAuditReplayReport",
    "MigrationImportError",
    "MigrationImportReport",
    "HandoffMigrationError",
    "HandoffReplayReport",
    "IdempotencyMigrationError",
    "IdempotencyReplayReport",
    "MemoryMigrationError",
    "MemoryReplayReport",
    "SQLiteSnapshot",
    "SnapshotIntegrityError",
    "SnapshotManifest",
    "SnapshotRecord",
    "PostgresCutoverStore",
    "export_sqlite_snapshot",
    "import_sqlite_event_snapshot",
    "load_sqlite_snapshot",
    "write_sqlite_snapshot",
    "attach_segment_in_transaction",
    "attach_segment_for_worker_in_transaction",
    "bootstrap_control_plane_epoch",
    "ClientCapabilityCasError",
    "ClientCapabilityConflictError",
    "PostgresClientCapabilityRegistry",
    "PostgresClientEffectDispatch",
    "PostgresClientEffectReceipts",
    "PostgresClientControlLeaseStore",
    "PostgresClientSessionRegistry",
    "read_control_plane_epoch",
    "rebuild_task_in_transaction",
    "rotate_control_plane_epoch",
]
_EXPORTS = {
    "AgentDefinitionEvalEvidence": (
        "agent_storage.postgres.agent_registry",
        "AgentDefinitionEvalEvidence",
    ),
    "AgentRegistryStorageError": (
        "agent_storage.postgres.agent_registry",
        "AgentRegistryStorageError",
    ),
    "PostgresAgentRegistry": ("agent_storage.postgres.agent_registry", "PostgresAgentRegistry"),
    "FencedAgentTaskStorePort": ("agent_storage.postgres.agent_tasks", "FencedAgentTaskStorePort"),
    "PostgresAgentTaskConflictError": (
        "agent_storage.postgres.agent_tasks",
        "PostgresAgentTaskConflictError",
    ),
    "PostgresAgentTaskStore": ("agent_storage.postgres.agent_tasks", "PostgresAgentTaskStore"),
    "attach_segment_for_worker_in_transaction": (
        "agent_storage.postgres.agent_tasks",
        "attach_segment_for_worker_in_transaction",
    ),
    "attach_segment_in_transaction": (
        "agent_storage.postgres.agent_tasks",
        "attach_segment_in_transaction",
    ),
    "rebuild_task_in_transaction": (
        "agent_storage.postgres.agent_tasks",
        "rebuild_task_in_transaction",
    ),
    "PostgresCloudArtifactPayloadStore": (
        "agent_storage.postgres.artifact_payloads",
        "PostgresCloudArtifactPayloadStore",
    ),
    "PostgresSessionArtifactReadStore": (
        "agent_storage.postgres.artifact_reads",
        "PostgresSessionArtifactReadStore",
    ),
    "ClientCapabilityCasError": (
        "agent_storage.postgres.client_capabilities",
        "ClientCapabilityCasError",
    ),
    "ClientCapabilityConflictError": (
        "agent_storage.postgres.client_capabilities",
        "ClientCapabilityConflictError",
    ),
    "PostgresClientCapabilityRegistry": (
        "agent_storage.postgres.client_capabilities",
        "PostgresClientCapabilityRegistry",
    ),
    "PostgresClientEffectDispatch": (
        "agent_storage.postgres.client_effects",
        "PostgresClientEffectDispatch",
    ),
    "PostgresClientEffectReceipts": (
        "agent_storage.postgres.client_effects",
        "PostgresClientEffectReceipts",
    ),
    "PostgresClientControlLeaseStore": (
        "agent_storage.postgres.client_sessions",
        "PostgresClientControlLeaseStore",
    ),
    "PostgresClientSessionRegistry": (
        "agent_storage.postgres.client_sessions",
        "PostgresClientSessionRegistry",
    ),
    "PostgresContextLifecycleConflictError": (
        "agent_storage.postgres.context_authority",
        "PostgresContextLifecycleConflictError",
    ),
    "PostgresContextLifecycleStore": (
        "agent_storage.postgres.context_lifecycle",
        "PostgresContextLifecycleStore",
    ),
    "PostgresContextMaterializationConflictError": (
        "agent_storage.postgres.context_materialization",
        "PostgresContextMaterializationConflictError",
    ),
    "PostgresContextMaterializationStore": (
        "agent_storage.postgres.context_materialization",
        "PostgresContextMaterializationStore",
    ),
    "PostgresDeliveryAuditStore": (
        "agent_storage.postgres.delivery_audit",
        "PostgresDeliveryAuditStore",
    ),
    "PostgresDeliveryTransactionStore": (
        "agent_storage.postgres.delivery_transaction",
        "PostgresDeliveryTransactionStore",
    ),
    "PostgresControlPlaneEpochError": (
        "agent_storage.postgres.epoch",
        "PostgresControlPlaneEpochError",
    ),
    "bootstrap_control_plane_epoch": (
        "agent_storage.postgres.epoch",
        "bootstrap_control_plane_epoch",
    ),
    "read_control_plane_epoch": ("agent_storage.postgres.epoch", "read_control_plane_epoch"),
    "rotate_control_plane_epoch": ("agent_storage.postgres.epoch", "rotate_control_plane_epoch"),
    "PostgresEventStore": ("agent_storage.postgres.events", "PostgresEventStore"),
    "PostgresGovernedMemoryStore": (
        "agent_storage.postgres.governed_memories",
        "PostgresGovernedMemoryStore",
    ),
    "GovernedMemoryImportError": (
        "agent_storage.postgres.governed_memory_import",
        "GovernedMemoryImportError",
    ),
    "GovernedMemoryImportQuarantine": (
        "agent_storage.postgres.governed_memory_import",
        "GovernedMemoryImportQuarantine",
    ),
    "GovernedMemoryImportReport": (
        "agent_storage.postgres.governed_memory_import",
        "GovernedMemoryImportReport",
    ),
    "import_sqlite_governed_memories": (
        "agent_storage.postgres.governed_memory_import",
        "import_sqlite_governed_memories",
    ),
    "HostAuthorityStorageError": ("agent_storage.postgres.host_auth", "HostAuthorityStorageError"),
    "HostGrantAttempt": ("agent_storage.postgres.host_auth", "HostGrantAttempt"),
    "HostGrantAuditRecord": ("agent_storage.postgres.host_auth", "HostGrantAuditRecord"),
    "HostGrantReplayDecision": ("agent_storage.postgres.host_auth", "HostGrantReplayDecision"),
    "HostRegistryBindingError": ("agent_storage.postgres.host_auth", "HostRegistryBindingError"),
    "HostRegistryRecord": ("agent_storage.postgres.host_auth", "HostRegistryRecord"),
    "PostgresHostAuthorityStore": (
        "agent_storage.postgres.host_auth",
        "PostgresHostAuthorityStore",
    ),
    "PostgresIdempotencyStore": ("agent_storage.postgres.idempotency", "PostgresIdempotencyStore"),
    "PostgresLeaseStore": ("agent_storage.postgres.leases", "PostgresLeaseStore"),
    "MemoryDeliveryClaim": ("agent_storage.postgres.memory_delivery", "MemoryDeliveryClaim"),
    "MemoryDeliveryConflictError": (
        "agent_storage.postgres.memory_delivery",
        "MemoryDeliveryConflictError",
    ),
    "MemoryDeliverySearchAdmission": (
        "agent_storage.postgres.memory_delivery",
        "MemoryDeliverySearchAdmission",
    ),
    "MemoryProviderMapping": ("agent_storage.postgres.memory_delivery", "MemoryProviderMapping"),
    "PostgresMemoryDeliveryLedger": (
        "agent_storage.postgres.memory_delivery",
        "PostgresMemoryDeliveryLedger",
    ),
    "PostgresMemoryDeliveryStore": (
        "agent_storage.postgres.memory_delivery",
        "PostgresMemoryDeliveryStore",
    ),
    "CutoverConflictError": ("agent_storage.postgres.migration_cutover", "CutoverConflictError"),
    "PostgresCutoverStore": ("agent_storage.postgres.migration_cutover", "PostgresCutoverStore"),
    "DeliveryAuditMigrationError": (
        "agent_storage.postgres.migration_delivery_audit",
        "DeliveryAuditMigrationError",
    ),
    "DeliveryAuditReplayReport": (
        "agent_storage.postgres.migration_delivery_audit",
        "DeliveryAuditReplayReport",
    ),
    "HandoffMigrationError": ("agent_storage.postgres.migration_handoff", "HandoffMigrationError"),
    "HandoffReplayReport": ("agent_storage.postgres.migration_handoff", "HandoffReplayReport"),
    "IdempotencyMigrationError": (
        "agent_storage.postgres.migration_idempotency",
        "IdempotencyMigrationError",
    ),
    "IdempotencyReplayReport": (
        "agent_storage.postgres.migration_idempotency",
        "IdempotencyReplayReport",
    ),
    "MemoryMigrationError": ("agent_storage.postgres.migration_memory", "MemoryMigrationError"),
    "MemoryReplayReport": ("agent_storage.postgres.migration_memory", "MemoryReplayReport"),
    "MigrationImportError": ("agent_storage.postgres.migration_recovery", "MigrationImportError"),
    "MigrationImportReport": ("agent_storage.postgres.migration_recovery", "MigrationImportReport"),
    "import_sqlite_event_snapshot": (
        "agent_storage.postgres.migration_recovery",
        "import_sqlite_event_snapshot",
    ),
    "apply_postgres_migrations": (
        "agent_storage.postgres.migration_runner",
        "apply_postgres_migrations",
    ),
    "SnapshotIntegrityError": (
        "agent_storage.postgres.migration_snapshot",
        "SnapshotIntegrityError",
    ),
    "SnapshotManifest": ("agent_storage.postgres.migration_snapshot", "SnapshotManifest"),
    "SnapshotRecord": ("agent_storage.postgres.migration_snapshot", "SnapshotRecord"),
    "SQLiteSnapshot": ("agent_storage.postgres.migration_snapshot", "SQLiteSnapshot"),
    "export_sqlite_snapshot": (
        "agent_storage.postgres.migration_snapshot",
        "export_sqlite_snapshot",
    ),
    "load_sqlite_snapshot": ("agent_storage.postgres.migration_snapshot", "load_sqlite_snapshot"),
    "write_sqlite_snapshot": ("agent_storage.postgres.migration_snapshot", "write_sqlite_snapshot"),
    "PostgresMigrationError": ("agent_storage.postgres.migration_types", "PostgresMigrationError"),
    "PostgresModelToolProjectionConflictError": (
        "agent_storage.postgres.model_tool_projections",
        "PostgresModelToolProjectionConflictError",
    ),
    "PostgresModelToolProjectionStore": (
        "agent_storage.postgres.model_tool_projections",
        "PostgresModelToolProjectionStore",
    ),
    "PostgresNativeMemoryGateway": (
        "agent_storage.postgres.native_memory",
        "PostgresNativeMemoryGateway",
    ),
    "NativeMemoryConflictError": (
        "agent_storage.postgres.native_memory_types",
        "NativeMemoryConflictError",
    ),
    "NativeMemoryError": ("agent_storage.postgres.native_memory_types", "NativeMemoryError"),
    "NativeMemoryMutation": ("agent_storage.postgres.native_memory_types", "NativeMemoryMutation"),
    "NativeMemoryNamespaceError": (
        "agent_storage.postgres.native_memory_types",
        "NativeMemoryNamespaceError",
    ),
    "NativeMemoryOperation": (
        "agent_storage.postgres.native_memory_types",
        "NativeMemoryOperation",
    ),
    "NativeMemoryRecallHit": (
        "agent_storage.postgres.native_memory_types",
        "NativeMemoryRecallHit",
    ),
    "NativeMemoryReset": ("agent_storage.postgres.native_memory_types", "NativeMemoryReset"),
    "NativeMemoryStaleGenerationError": (
        "agent_storage.postgres.native_memory_types",
        "NativeMemoryStaleGenerationError",
    ),
    "PostgresEffectDispatchStore": ("agent_storage.postgres.outbox", "PostgresEffectDispatchStore"),
    "PostgresProjectionConflictError": (
        "agent_storage.postgres.projections",
        "PostgresProjectionConflictError",
    ),
    "PostgresProjectionStore": ("agent_storage.postgres.projections", "PostgresProjectionStore"),
    "PostgresProviderContinuationConflictError": (
        "agent_storage.postgres.provider_continuations",
        "PostgresProviderContinuationConflictError",
    ),
    "PostgresProviderContinuationStore": (
        "agent_storage.postgres.provider_continuations",
        "PostgresProviderContinuationStore",
    ),
    "PostgresHandoffDispatchStore": (
        "agent_storage.postgres.session_handoff_dispatch",
        "PostgresHandoffDispatchStore",
    ),
    "PostgresSessionHandoffStore": (
        "agent_storage.postgres.session_handoffs",
        "PostgresSessionHandoffStore",
    ),
    "PostgresSessionHistory": ("agent_storage.postgres.session_history", "PostgresSessionHistory"),
    "PostgresTaskScheduleFiringStore": (
        "agent_storage.postgres.task_schedule_firings",
        "PostgresTaskScheduleFiringStore",
    ),
    "TaskScheduleStorageIntegrityError": (
        "agent_storage.postgres.task_schedule_rows",
        "TaskScheduleStorageIntegrityError",
    ),
    "PostgresTaskScheduleStore": (
        "agent_storage.postgres.task_schedules",
        "PostgresTaskScheduleStore",
    ),
    "PostgresUserPersonalizationStore": (
        "agent_storage.postgres.user_personalization",
        "PostgresUserPersonalizationStore",
    ),
    "PostgresWorkspaceControlStore": (
        "agent_storage.postgres.workspace_control",
        "PostgresWorkspaceControlStore",
    ),
    "PostgresWorkspaceProjectionConflictError": (
        "agent_storage.postgres.workspaces",
        "PostgresWorkspaceProjectionConflictError",
    ),
    "PostgresWorkspaceProjectionStore": (
        "agent_storage.postgres.workspaces",
        "PostgresWorkspaceProjectionStore",
    ),
}


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, symbol = _EXPORTS[name]
    value = getattr(_import_module(module, __name__), symbol)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

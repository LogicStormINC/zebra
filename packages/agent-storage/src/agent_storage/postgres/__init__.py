"""PostgreSQL adapters used by the explicit cloud control-plane composition.

Lazy re-exports (PEP 562): this subpackage root previously pulled every
postgres adapter (~1.1s of session-child import cost, CA-HA-03 D1).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Static-analysis view only; never executed at runtime.
    from agent_storage.postgres.agent_registry import (
        AgentDefinitionEvalEvidence,
        AgentRegistryStorageError,
        PostgresAgentRegistry,
    )
    from agent_storage.postgres.agent_tasks import (
        FencedAgentTaskStorePort,
        PostgresAgentTaskConflictError,
        PostgresAgentTaskStore,
        attach_segment_for_worker_in_transaction,
        attach_segment_in_transaction,
        rebuild_task_in_transaction,
    )
    from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
    from agent_storage.postgres.artifact_reads import PostgresSessionArtifactReadStore
    from agent_storage.postgres.client_capabilities import (
        ClientCapabilityCasError,
        ClientCapabilityConflictError,
        PostgresClientCapabilityRegistry,
    )
    from agent_storage.postgres.client_effects import (
        PostgresClientEffectDispatch,
        PostgresClientEffectReceipts,
    )
    from agent_storage.postgres.client_sessions import (
        PostgresClientControlLeaseStore,
        PostgresClientSessionRegistry,
    )
    from agent_storage.postgres.context_authority import PostgresContextLifecycleConflictError
    from agent_storage.postgres.context_lifecycle import (
        PostgresContextLifecycleStore,
    )
    from agent_storage.postgres.context_materialization import (
        PostgresContextMaterializationConflictError,
        PostgresContextMaterializationStore,
    )
    from agent_storage.postgres.delivery_audit import PostgresDeliveryAuditStore
    from agent_storage.postgres.delivery_transaction import PostgresDeliveryTransactionStore
    from agent_storage.postgres.epoch import (
        PostgresControlPlaneEpochError,
        bootstrap_control_plane_epoch,
        read_control_plane_epoch,
        rotate_control_plane_epoch,
    )
    from agent_storage.postgres.events import PostgresEventStore
    from agent_storage.postgres.governed_memories import PostgresGovernedMemoryStore
    from agent_storage.postgres.governed_memory_import import (
        GovernedMemoryImportError,
        GovernedMemoryImportQuarantine,
        GovernedMemoryImportReport,
        import_sqlite_governed_memories,
    )
    from agent_storage.postgres.host_auth import (
        HostAuthorityStorageError,
        HostGrantAttempt,
        HostGrantAuditRecord,
        HostGrantReplayDecision,
        HostRegistryBindingError,
        HostRegistryRecord,
        PostgresHostAuthorityStore,
    )
    from agent_storage.postgres.idempotency import PostgresIdempotencyStore
    from agent_storage.postgres.leases import PostgresLeaseStore
    from agent_storage.postgres.memory_delivery import (
        MemoryDeliveryClaim,
        MemoryDeliveryConflictError,
        MemoryDeliverySearchAdmission,
        MemoryProviderMapping,
        PostgresMemoryDeliveryLedger,
        PostgresMemoryDeliveryStore,
    )
    from agent_storage.postgres.migration_cutover import CutoverConflictError, PostgresCutoverStore
    from agent_storage.postgres.migration_delivery_audit import (
        DeliveryAuditMigrationError,
        DeliveryAuditReplayReport,
    )
    from agent_storage.postgres.migration_handoff import (
        HandoffMigrationError,
        HandoffReplayReport,
    )
    from agent_storage.postgres.migration_idempotency import (
        IdempotencyMigrationError,
        IdempotencyReplayReport,
    )
    from agent_storage.postgres.migration_memory import MemoryMigrationError, MemoryReplayReport
    from agent_storage.postgres.migration_recovery import (
        MigrationImportError,
        MigrationImportReport,
        import_sqlite_event_snapshot,
    )
    from agent_storage.postgres.migration_runner import apply_postgres_migrations
    from agent_storage.postgres.migration_snapshot import (
        SnapshotIntegrityError,
        SnapshotManifest,
        SnapshotRecord,
        SQLiteSnapshot,
        export_sqlite_snapshot,
        load_sqlite_snapshot,
        write_sqlite_snapshot,
    )
    from agent_storage.postgres.migration_types import PostgresMigrationError
    from agent_storage.postgres.model_tool_projections import (
        PostgresModelToolProjectionConflictError,
        PostgresModelToolProjectionStore,
    )
    from agent_storage.postgres.native_memory import PostgresNativeMemoryGateway
    from agent_storage.postgres.native_memory_types import (
        NativeMemoryConflictError,
        NativeMemoryError,
        NativeMemoryMutation,
        NativeMemoryNamespaceError,
        NativeMemoryOperation,
        NativeMemoryRecallHit,
        NativeMemoryReset,
        NativeMemoryStaleGenerationError,
    )
    from agent_storage.postgres.outbox import PostgresEffectDispatchStore
    from agent_storage.postgres.projections import (
        PostgresProjectionConflictError,
        PostgresProjectionStore,
    )
    from agent_storage.postgres.provider_continuations import (
        PostgresProviderContinuationConflictError,
        PostgresProviderContinuationStore,
    )
    from agent_storage.postgres.session_handoff_dispatch import PostgresHandoffDispatchStore
    from agent_storage.postgres.session_handoffs import PostgresSessionHandoffStore
    from agent_storage.postgres.session_history import PostgresSessionHistory
    from agent_storage.postgres.task_schedule_firings import PostgresTaskScheduleFiringStore
    from agent_storage.postgres.task_schedule_rows import TaskScheduleStorageIntegrityError
    from agent_storage.postgres.task_schedules import PostgresTaskScheduleStore
    from agent_storage.postgres.user_personalization import PostgresUserPersonalizationStore
    from agent_storage.postgres.workspace_control import (
        PostgresWorkspaceControlStore,
    )
    from agent_storage.postgres.workspaces import (
        PostgresWorkspaceProjectionConflictError,
        PostgresWorkspaceProjectionStore,
    )

_LAZY_EXPORTS: dict[str, str] = {
    "AgentDefinitionEvalEvidence": "agent_storage.postgres.agent_registry",
    "AgentRegistryStorageError": "agent_storage.postgres.agent_registry",
    "ClientCapabilityCasError": "agent_storage.postgres.client_capabilities",
    "ClientCapabilityConflictError": "agent_storage.postgres.client_capabilities",
    "CutoverConflictError": "agent_storage.postgres.migration_cutover",
    "DeliveryAuditMigrationError": "agent_storage.postgres.migration_delivery_audit",
    "DeliveryAuditReplayReport": "agent_storage.postgres.migration_delivery_audit",
    "FencedAgentTaskStorePort": "agent_storage.postgres.agent_tasks",
    "GovernedMemoryImportError": "agent_storage.postgres.governed_memory_import",
    "GovernedMemoryImportQuarantine": "agent_storage.postgres.governed_memory_import",
    "GovernedMemoryImportReport": "agent_storage.postgres.governed_memory_import",
    "HandoffMigrationError": "agent_storage.postgres.migration_handoff",
    "HandoffReplayReport": "agent_storage.postgres.migration_handoff",
    "HostAuthorityStorageError": "agent_storage.postgres.host_auth",
    "HostGrantAttempt": "agent_storage.postgres.host_auth",
    "HostGrantAuditRecord": "agent_storage.postgres.host_auth",
    "HostGrantReplayDecision": "agent_storage.postgres.host_auth",
    "HostRegistryBindingError": "agent_storage.postgres.host_auth",
    "HostRegistryRecord": "agent_storage.postgres.host_auth",
    "IdempotencyMigrationError": "agent_storage.postgres.migration_idempotency",
    "IdempotencyReplayReport": "agent_storage.postgres.migration_idempotency",
    "MemoryDeliveryClaim": "agent_storage.postgres.memory_delivery",
    "MemoryDeliveryConflictError": "agent_storage.postgres.memory_delivery",
    "MemoryDeliverySearchAdmission": "agent_storage.postgres.memory_delivery",
    "MemoryMigrationError": "agent_storage.postgres.migration_memory",
    "MemoryProviderMapping": "agent_storage.postgres.memory_delivery",
    "MemoryReplayReport": "agent_storage.postgres.migration_memory",
    "MigrationImportError": "agent_storage.postgres.migration_recovery",
    "MigrationImportReport": "agent_storage.postgres.migration_recovery",
    "NativeMemoryConflictError": "agent_storage.postgres.native_memory_types",
    "NativeMemoryError": "agent_storage.postgres.native_memory_types",
    "NativeMemoryMutation": "agent_storage.postgres.native_memory_types",
    "NativeMemoryNamespaceError": "agent_storage.postgres.native_memory_types",
    "NativeMemoryOperation": "agent_storage.postgres.native_memory_types",
    "NativeMemoryRecallHit": "agent_storage.postgres.native_memory_types",
    "NativeMemoryReset": "agent_storage.postgres.native_memory_types",
    "NativeMemoryStaleGenerationError": "agent_storage.postgres.native_memory_types",
    "PostgresAgentRegistry": "agent_storage.postgres.agent_registry",
    "PostgresAgentTaskConflictError": "agent_storage.postgres.agent_tasks",
    "PostgresAgentTaskStore": "agent_storage.postgres.agent_tasks",
    "PostgresClientCapabilityRegistry": "agent_storage.postgres.client_capabilities",
    "PostgresClientControlLeaseStore": "agent_storage.postgres.client_sessions",
    "PostgresClientEffectDispatch": "agent_storage.postgres.client_effects",
    "PostgresClientEffectReceipts": "agent_storage.postgres.client_effects",
    "PostgresClientSessionRegistry": "agent_storage.postgres.client_sessions",
    "PostgresCloudArtifactPayloadStore": "agent_storage.postgres.artifact_payloads",
    "PostgresContextLifecycleConflictError": "agent_storage.postgres.context_authority",
    "PostgresContextLifecycleStore": "agent_storage.postgres.context_lifecycle",
    "PostgresContextMaterializationConflictError": "agent_storage.postgres.context_materialization",
    "PostgresContextMaterializationStore": "agent_storage.postgres.context_materialization",
    "PostgresControlPlaneEpochError": "agent_storage.postgres.epoch",
    "PostgresCutoverStore": "agent_storage.postgres.migration_cutover",
    "PostgresDeliveryAuditStore": "agent_storage.postgres.delivery_audit",
    "PostgresDeliveryTransactionStore": "agent_storage.postgres.delivery_transaction",
    "PostgresEffectDispatchStore": "agent_storage.postgres.outbox",
    "PostgresEventStore": "agent_storage.postgres.events",
    "PostgresGovernedMemoryStore": "agent_storage.postgres.governed_memories",
    "PostgresHandoffDispatchStore": "agent_storage.postgres.session_handoff_dispatch",
    "PostgresHostAuthorityStore": "agent_storage.postgres.host_auth",
    "PostgresIdempotencyStore": "agent_storage.postgres.idempotency",
    "PostgresLeaseStore": "agent_storage.postgres.leases",
    "PostgresMemoryDeliveryLedger": "agent_storage.postgres.memory_delivery",
    "PostgresMemoryDeliveryStore": "agent_storage.postgres.memory_delivery",
    "PostgresMigrationError": "agent_storage.postgres.migration_types",
    "PostgresModelToolProjectionConflictError": "agent_storage.postgres.model_tool_projections",
    "PostgresModelToolProjectionStore": "agent_storage.postgres.model_tool_projections",
    "PostgresNativeMemoryGateway": "agent_storage.postgres.native_memory",
    "PostgresProjectionConflictError": "agent_storage.postgres.projections",
    "PostgresProjectionStore": "agent_storage.postgres.projections",
    "PostgresProviderContinuationConflictError": "agent_storage.postgres.provider_continuations",
    "PostgresProviderContinuationStore": "agent_storage.postgres.provider_continuations",
    "PostgresSessionArtifactReadStore": "agent_storage.postgres.artifact_reads",
    "PostgresSessionHandoffStore": "agent_storage.postgres.session_handoffs",
    "PostgresSessionHistory": "agent_storage.postgres.session_history",
    "PostgresTaskScheduleFiringStore": "agent_storage.postgres.task_schedule_firings",
    "PostgresTaskScheduleStore": "agent_storage.postgres.task_schedules",
    "PostgresUserPersonalizationStore": "agent_storage.postgres.user_personalization",
    "PostgresWorkspaceControlStore": "agent_storage.postgres.workspace_control",
    "PostgresWorkspaceProjectionConflictError": "agent_storage.postgres.workspaces",
    "PostgresWorkspaceProjectionStore": "agent_storage.postgres.workspaces",
    "SQLiteSnapshot": "agent_storage.postgres.migration_snapshot",
    "SnapshotIntegrityError": "agent_storage.postgres.migration_snapshot",
    "SnapshotManifest": "agent_storage.postgres.migration_snapshot",
    "SnapshotRecord": "agent_storage.postgres.migration_snapshot",
    "TaskScheduleStorageIntegrityError": "agent_storage.postgres.task_schedule_rows",
    "apply_postgres_migrations": "agent_storage.postgres.migration_runner",
    "attach_segment_for_worker_in_transaction": "agent_storage.postgres.agent_tasks",
    "attach_segment_in_transaction": "agent_storage.postgres.agent_tasks",
    "bootstrap_control_plane_epoch": "agent_storage.postgres.epoch",
    "export_sqlite_snapshot": "agent_storage.postgres.migration_snapshot",
    "import_sqlite_event_snapshot": "agent_storage.postgres.migration_recovery",
    "import_sqlite_governed_memories": "agent_storage.postgres.governed_memory_import",
    "load_sqlite_snapshot": "agent_storage.postgres.migration_snapshot",
    "read_control_plane_epoch": "agent_storage.postgres.epoch",
    "rebuild_task_in_transaction": "agent_storage.postgres.agent_tasks",
    "rotate_control_plane_epoch": "agent_storage.postgres.epoch",
    "write_sqlite_snapshot": "agent_storage.postgres.migration_snapshot",
}


def __getattr__(name: str) -> object:
    """Resolve a re-exported attribute on first access (PEP 562)."""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_path), name)
    globals()[name] = value  # Cache: subsequent lookups bypass this hook.
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


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

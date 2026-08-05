"""PostgreSQL adapters used by the explicit cloud control-plane composition."""

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
from agent_storage.postgres.context_lifecycle import (
    PostgresContextLifecycleConflictError,
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
from agent_storage.postgres.native_memory import (
    NativeMemoryConflictError,
    NativeMemoryError,
    NativeMemoryMutation,
    NativeMemoryNamespaceError,
    NativeMemoryOperation,
    NativeMemoryRecallHit,
    NativeMemoryReset,
    NativeMemoryStaleGenerationError,
    PostgresNativeMemoryGateway,
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
from agent_storage.postgres.workspaces import (
    PostgresWorkspaceProjectionConflictError,
    PostgresWorkspaceProjectionStore,
)

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
    "read_control_plane_epoch",
    "rebuild_task_in_transaction",
    "rotate_control_plane_epoch",
]

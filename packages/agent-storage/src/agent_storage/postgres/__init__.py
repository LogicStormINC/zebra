"""PostgreSQL control-plane adapters that remain inactive until full composition."""

from agent_storage.postgres.agent_tasks import (
    PostgresAgentTaskConflictError,
    PostgresAgentTaskStore,
    attach_segment_in_transaction,
    rebuild_task_in_transaction,
)
from agent_storage.postgres.epoch import (
    PostgresControlPlaneEpochError,
    bootstrap_control_plane_epoch,
    read_control_plane_epoch,
    rotate_control_plane_epoch,
)
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.leases import PostgresLeaseStore
from agent_storage.postgres.migrations import (
    PostgresMigrationError,
    apply_postgres_migrations,
)
from agent_storage.postgres.outbox import PostgresEffectDispatchStore
from agent_storage.postgres.projections import (
    PostgresProjectionConflictError,
    PostgresProjectionStore,
)
from agent_storage.postgres.workspaces import (
    PostgresWorkspaceProjectionConflictError,
    PostgresWorkspaceProjectionStore,
)

__all__ = [
    "PostgresAgentTaskConflictError",
    "PostgresAgentTaskStore",
    "PostgresEventStore",
    "PostgresEffectDispatchStore",
    "PostgresControlPlaneEpochError",
    "PostgresLeaseStore",
    "PostgresMigrationError",
    "PostgresProjectionConflictError",
    "PostgresProjectionStore",
    "PostgresWorkspaceProjectionConflictError",
    "PostgresWorkspaceProjectionStore",
    "apply_postgres_migrations",
    "attach_segment_in_transaction",
    "bootstrap_control_plane_epoch",
    "read_control_plane_epoch",
    "rebuild_task_in_transaction",
    "rotate_control_plane_epoch",
]

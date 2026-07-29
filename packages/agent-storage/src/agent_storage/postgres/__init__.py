"""PostgreSQL control-plane adapters that remain inactive until full composition."""

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
    "bootstrap_control_plane_epoch",
    "read_control_plane_epoch",
    "rotate_control_plane_epoch",
]

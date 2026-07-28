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
from agent_storage.postgres.projections import (
    PostgresProjectionConflictError,
    PostgresProjectionStore,
)

__all__ = [
    "PostgresEventStore",
    "PostgresControlPlaneEpochError",
    "PostgresLeaseStore",
    "PostgresMigrationError",
    "PostgresProjectionConflictError",
    "PostgresProjectionStore",
    "apply_postgres_migrations",
    "bootstrap_control_plane_epoch",
    "read_control_plane_epoch",
    "rotate_control_plane_epoch",
]

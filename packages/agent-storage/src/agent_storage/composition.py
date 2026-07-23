from dataclasses import dataclass
from pathlib import Path

from agent_core.ports import (
    AgentTaskPort,
    EventStorePort,
    LeaseStorePort,
    ProjectionStorePort,
    WorkspaceProjectionStorePort,
)

from agent_storage.agent_tasks import SQLiteAgentTaskStore
from agent_storage.leases import SQLiteLeaseStore
from agent_storage.projections import SQLiteProjectionStore
from agent_storage.sqlite import SQLiteEventStore
from agent_storage.workspaces import SQLiteWorkspaceProjectionStore


@dataclass(frozen=True, slots=True)
class ControlPlaneStores:
    events: EventStorePort
    sessions: ProjectionStorePort
    workspaces: WorkspaceProjectionStorePort
    tasks: AgentTaskPort
    leases: LeaseStorePort
    legacy_database_path: Path | None = None


def sqlite_control_plane_stores(database_path: str | Path) -> ControlPlaneStores:
    local_path = Path(database_path)
    if str(local_path) == ":memory:":
        raise ValueError(
            "sqlite control-plane composition requires a filesystem-backed database"
        )
    return ControlPlaneStores(
        events=SQLiteEventStore(local_path),
        sessions=SQLiteProjectionStore(local_path),
        workspaces=SQLiteWorkspaceProjectionStore(local_path),
        tasks=SQLiteAgentTaskStore(local_path),
        leases=SQLiteLeaseStore(local_path),
        legacy_database_path=_database_identity(local_path),
    )


def require_legacy_database_coherence(
    stores: ControlPlaneStores,
    database_path: str | Path,
) -> None:
    """Reject split backends until every durable collaborator is composed."""
    expected_path = _database_identity(Path(database_path))
    if stores.legacy_database_path != expected_path:
        raise ValueError(
            "control-plane stores must share database_path until context, handoff, "
            "memory and effect stores join the composition root"
        )


def _database_identity(database_path: Path) -> Path:
    return database_path.resolve()
